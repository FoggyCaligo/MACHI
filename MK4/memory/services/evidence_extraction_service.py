from __future__ import annotations

import json
from dataclasses import dataclass

from tools.ollama_client import OllamaClient
from prompts.prompt_loader import load_prompt_text


@dataclass
class ExtractionRunResult:
    text: str
    error: str | None = None
    retried: bool = False


class EvidenceExtractionService:
    def __init__(self, timeout: int = 120, num_predict: int = 256, retry_num_predict: int = 192) -> None:
        self.client = OllamaClient(timeout=timeout, num_predict=num_predict)
        self.retry_client = OllamaClient(timeout=timeout, num_predict=retry_num_predict)

    def build_messages(self, system_prompt_path: str, user_prompt: str) -> list[dict]:
        system_prompt = load_prompt_text(system_prompt_path)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def run_extract(
        self,
        *,
        system_prompt_path: str,
        user_prompt: str,
        model: str | None = None,
        retry_user_prompt: str | None = None,
        require_complete: bool = True,
    ) -> ExtractionRunResult:
        messages = self.build_messages(system_prompt_path, user_prompt)
        try:
            answer = self.client.chat(
                messages,
                model=model,
                require_complete=require_complete,
                truncated_notice=None if require_complete else "",
            ).strip()
            return ExtractionRunResult(text=answer)
        except RuntimeError as exc:
            error_text = str(exc)
            if not retry_user_prompt or 'TRUNCATED_REPLY_LENGTH' not in error_text:
                return ExtractionRunResult(text="", error=error_text)

        retry_messages = self.build_messages(system_prompt_path, retry_user_prompt)
        try:
            answer = self.retry_client.chat(
                retry_messages,
                model=model,
                require_complete=require_complete,
                truncated_notice=None if require_complete else "",
            ).strip()
            return ExtractionRunResult(text=answer, error='retried_after_truncation', retried=True)
        except RuntimeError as exc:
            return ExtractionRunResult(text="", error=str(exc), retried=True)

    def parse_json_array(self, text: str) -> list[dict]:
        raw = (text or "").strip()
        if not raw:
            return []

        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1 or end < start:
            return []

        raw = raw[start:end + 1]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def parse_profile_candidates(
        self,
        text: str,
        *,
        normalize_source_strength,
        include_source_file_paths: bool = False,
    ) -> list[dict]:
        data = self.parse_json_array(text)
        result: list[dict] = []

        for item in data:
            topic = str(item.get("topic") or "").strip()
            candidate_content = str(item.get("candidate_content") or "").strip()
            source_strength = normalize_source_strength(item.get("source_strength"))
            evidence_text = str(item.get("evidence_text") or "").strip()

            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            if not topic or not candidate_content:
                continue

            parsed = {
                "topic": topic,
                "candidate_content": candidate_content,
                "source_strength": source_strength,
                "confidence": max(0.0, min(confidence, 1.0)),
                "evidence_text": evidence_text,
            }

            if include_source_file_paths:
                source_file_paths = item.get("source_file_paths") or []
                if not isinstance(source_file_paths, list):
                    source_file_paths = []
                parsed["source_file_paths"] = [str(x) for x in source_file_paths]

            result.append(parsed)

        return result
