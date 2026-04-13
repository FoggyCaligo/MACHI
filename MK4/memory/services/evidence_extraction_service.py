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

    def _strip_code_fence(self, raw: str) -> str:
        if not raw.startswith("```"):
            return raw

        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()


    def parse_json_array_with_meta(self, text: str) -> tuple[list[dict], dict]:
        original = (text or "").strip()
        if not original:
            return [], {
                "parse_status": "empty_response",
                "container_type": "none",
                "raw_item_count": 0,
                "dict_item_count": 0,
                "raw_preview": "",
            }

        raw = self._strip_code_fence(original)
        parse_target = raw
        container_type = "array"

        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end >= start:
            parse_target = raw[start:end + 1]
        else:
            obj_start = raw.find("{")
            obj_end = raw.rfind("}")
            if obj_start != -1 and obj_end != -1 and obj_end >= obj_start:
                parse_target = raw[obj_start:obj_end + 1]
                container_type = "object"
            else:
                return [], {
                    "parse_status": "json_bracket_not_found",
                    "container_type": "unknown",
                    "raw_item_count": 0,
                    "dict_item_count": 0,
                    "raw_preview": raw[:240],
                }

        try:
            data = json.loads(parse_target)
        except json.JSONDecodeError as exc:
            return [], {
                "parse_status": "json_decode_error",
                "container_type": container_type,
                "raw_item_count": 0,
                "dict_item_count": 0,
                "parse_error": str(exc),
                "raw_preview": parse_target[:240],
            }

        if container_type == "object" and isinstance(data, dict):
            data = [data]

        if not isinstance(data, list):
            return [], {
                "parse_status": "decoded_non_list",
                "container_type": container_type,
                "raw_item_count": 0,
                "dict_item_count": 0,
                "raw_preview": str(data)[:240],
            }

        items = [item for item in data if isinstance(item, dict)]
        return items, {
            "parse_status": "ok",
            "container_type": container_type,
            "raw_item_count": len(data),
            "dict_item_count": len(items),
            "raw_preview": parse_target[:240],
        }

    def parse_json_array(self, text: str) -> list[dict]:
        data, _meta = self.parse_json_array_with_meta(text)
        return data
    
    def parse_profile_candidates(
        self,
        text: str,
        *,
        normalize_source_strength,
        include_source_file_paths: bool = False,
    ) -> list[dict]:
        result, _meta = self.parse_profile_candidates_with_meta(
            text,
            normalize_source_strength=normalize_source_strength,
            include_source_file_paths=include_source_file_paths,
        )
        return result


    def parse_profile_candidates_with_meta(
        self,
        text: str,
        *,
        normalize_source_strength,
        include_source_file_paths: bool = False,
    ) -> tuple[list[dict], dict]:
        data, meta = self.parse_json_array_with_meta(text)
        result: list[dict] = []
        dropped_count = 0

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
                dropped_count += 1
                continue

            parsed = {
                "topic": topic,
                "candidate_content": candidate_content,
                "source_strength": source_strength,
                "confidence": max(0.0, min(confidence, 1.0)),
                "evidence_text": evidence_text,
                "direct_confirm": bool(item.get("direct_confirm")),
            }

            if include_source_file_paths:
                source_file_paths = item.get("source_file_paths") or []
                if not isinstance(source_file_paths, list):
                    source_file_paths = []
                parsed["source_file_paths"] = [str(x) for x in source_file_paths]

            result.append(parsed)

        meta = {
            **meta,
            "valid_candidate_count": len(result),
            "dropped_candidate_count": dropped_count,
        }
        return result, meta