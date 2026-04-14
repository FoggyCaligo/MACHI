from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.entities.conclusion import CoreConclusion, DerivedActionLayer

OLLAMA_CHAT_URL = 'http://127.0.0.1:11434/api/chat'


class OllamaVerbalizerError(RuntimeError):
    pass


@dataclass(slots=True)
class OllamaVerbalizer:
    base_url: str = OLLAMA_CHAT_URL
    timeout_seconds: float = 20.0

    def verbalize(
        self,
        *,
        model_name: str,
        conclusion: CoreConclusion,
        action_layer: DerivedActionLayer,
    ) -> str:
        payload = {
            'model': model_name,
            'stream': False,
            'messages': [
                {
                    'role': 'system',
                    'content': self._build_system_prompt(),
                },
                {
                    'role': 'user',
                    'content': self._build_user_prompt(conclusion, action_layer),
                },
            ],
            'options': {
                'temperature': 0.2,
            },
        }
        request = Request(
            self.base_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='ignore')
            raise OllamaVerbalizerError(f'OLLAMA HTTP {exc.code}: {body or exc.reason}') from exc
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaVerbalizerError(str(exc)) from exc

        message = raw.get('message') or {}
        content = str(message.get('content') or '').strip()
        if not content:
            raise OllamaVerbalizerError('OLLAMA returned empty content')
        return content

    def _build_system_prompt(self) -> str:
        return (
            '너는 MK5의 사용자 응답용 언어화 모델이다. '
            '주어진 core conclusion과 derived action layer를 바탕으로 사용자에게 보낼 최종 한국어 답변만 생성한다. '
            '새로운 사실을 추가하지 말고, 그래프에 없는 내용을 지어내지 마라. '
            'internal explanation, debug, node, edge, trust, revision 같은 내부 용어를 본문에 직접 노출하지 마라. '
            '응답은 자연스럽고 짧게 하되, 불확실하면 모른다고 말해라. '
            '불필요한 목록, 로그, 수치 나열을 피하고, 사용자의 질문에 바로 답하라.'
        )

    def _build_user_prompt(self, conclusion: CoreConclusion, action_layer: DerivedActionLayer) -> str:
        payload: dict[str, Any] = {
            'user_input_summary': conclusion.user_input_summary,
            'inferred_intent': conclusion.inferred_intent,
            'explanation_summary': conclusion.explanation_summary,
            'activated_concept_count': len(conclusion.activated_concepts),
            'key_relation_count': len(conclusion.key_relations),
            'conflict_count': len(conclusion.detected_conflicts),
            'response_mode': action_layer.response_mode,
            'answer_goal': action_layer.answer_goal,
            'suggested_actions': action_layer.suggested_actions,
            'do_not_claim': action_layer.do_not_claim,
            'tone_hint': action_layer.tone_hint,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
