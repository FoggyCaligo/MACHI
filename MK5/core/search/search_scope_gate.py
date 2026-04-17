from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from config import (
    SEARCH_SCOPE_GATE_NUM_PREDICT,
    SEARCH_SCOPE_GATE_TEMPERATURE,
    SEARCH_SCOPE_GATE_TIMEOUT_SECONDS,
    build_ollama_options,
)
from core.entities.conclusion import CoreConclusion
from core.entities.thought_view import ThoughtView
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
)
from tools.prompt_loader import load_prompt_text


class SearchScopeGateError(RuntimeError):
    pass


@dataclass(slots=True)
class SearchScopeGateDecision:
    needs_external_search: bool
    scope: str
    reason: str
    confidence: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            'needs_external_search': self.needs_external_search,
            'scope': self.scope,
            'reason': self.reason,
            'confidence': self.confidence,
            **self.metadata,
        }


@dataclass(slots=True)
class SearchScopeGate:
    client: OllamaClient | None = None
    system_prompt_path: str = 'prompts/system/search_scope_gate_system_prompt.txt'
    user_prompt_path: str = 'prompts/search/search_scope_gate_prompt.txt'

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=SEARCH_SCOPE_GATE_TIMEOUT_SECONDS)

    def decide(
        self,
        *,
        model_name: str,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        target_terms: list[str],
    ) -> SearchScopeGateDecision:
        if not model_name.strip() or model_name == 'mk5-graph-core':
            raise SearchScopeGateError('search scope gate requires a selectable LLM model')
        try:
            result = self.client.chat(
                model_name=model_name,
                messages=[
                    {'role': 'system', 'content': self._build_system_prompt()},
                    {
                        'role': 'user',
                        'content': self._build_user_prompt(
                            message=message,
                            thought_view=thought_view,
                            conclusion=conclusion,
                            target_terms=target_terms,
                        ),
                    },
                ],
                stream=False,
                options=build_ollama_options(
                    temperature=SEARCH_SCOPE_GATE_TEMPERATURE,
                    num_predict=SEARCH_SCOPE_GATE_NUM_PREDICT,
                ),
                response_format='json',
            )
        except OllamaModelNotFoundError as exc:
            raise SearchScopeGateError(str(exc)) from exc
        except (OllamaClientError, OllamaResponseError) as exc:
            raise SearchScopeGateError(str(exc)) from exc

        payload = self._parse_json(result.content)
        needs_external_search = bool(
            payload.get('needs_external_search')
            if 'needs_external_search' in payload
            else payload.get('external_grounding_needed')
        )
        scope = ' '.join(str(payload.get('scope') or '').split()).strip() or ('world_grounding' if needs_external_search else 'local_graph_only')
        reason = ' '.join(str(payload.get('reason') or '').split()).strip() or (
            '질문은 외부 세계 사실 확인이 필요한 요청이다.'
            if needs_external_search
            else '질문은 현재 대화와 활성 그래프 범위 안에서 답할 수 있다.'
        )
        confidence = ' '.join(str(payload.get('confidence') or '').split()).strip()
        return SearchScopeGateDecision(
            needs_external_search=needs_external_search,
            scope=scope,
            reason=reason,
            confidence=confidence,
            metadata={
                'target_terms': self._dedupe_items(target_terms, limit=8),
            },
        )

    def _build_system_prompt(self) -> str:
        return load_prompt_text(self.system_prompt_path)

    def _build_user_prompt(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        target_terms: list[str],
    ) -> str:
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input=message,
            inferred_intent=conclusion.inferred_intent,
        )

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- 없음'
        return '\n'.join(f'- {item}' for item in items[:8])

    def _parse_json(self, text: str) -> dict[str, Any]:
        raw = str(text or '').strip()
        candidates = [raw]
        fenced = self._extract_fenced_json(raw)
        if fenced:
            candidates.append(fenced)
        bracketed = self._extract_braced_json(raw)
        if bracketed and bracketed not in candidates:
            candidates.append(bracketed)

        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise SearchScopeGateError('search scope gate returned invalid JSON')

    def _extract_fenced_json(self, text: str) -> str:
        marker = '```'
        if marker not in text:
            return ''
        parts = text.split(marker)
        for chunk in parts[1:]:
            normalized = chunk.strip()
            if normalized.startswith('json'):
                normalized = normalized[4:].strip()
            if normalized.startswith('{') and normalized.endswith('}'):
                return normalized
        return ''

    def _extract_braced_json(self, text: str) -> str:
        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end == -1 or end <= start:
            return ''
        return text[start:end + 1]

    def _dedupe_items(self, items: list[Any], *, limit: int) -> list[str]:
        tokens: list[str] = []
        for item in items:
            token = ' '.join(str(item or '').split()).strip()
            if not token or token in tokens:
                continue
            tokens.append(token)
            if len(tokens) >= limit:
                break
        return tokens
