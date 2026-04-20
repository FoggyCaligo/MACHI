from __future__ import annotations

from dataclasses import dataclass, field

from core.entities.conclusion import DerivedActionLayer
from core.entities.conclusion_view import ConclusionView


@dataclass(slots=True)
class MeaningPreservationResult:
    preserved: bool
    severity: str
    recommended_action: str
    violations: list[str] = field(default_factory=list)
    safe_response: str = ''
    reason: str = ''


@dataclass(slots=True)
class MeaningPreserver:
    def evaluate(
        self,
        *,
        conclusion: ConclusionView,
        action_layer: DerivedActionLayer,
        user_response: str,
    ) -> MeaningPreservationResult:
        search_context = conclusion.metadata.get('search_context', {}) if isinstance(conclusion.metadata, dict) else {}
        need_search = bool(search_context.get('need_search'))
        attempted = bool(search_context.get('attempted'))
        no_evidence_found = bool(search_context.get('no_evidence_found'))
        search_error = ' '.join(str(search_context.get('error') or '').split()).strip()
        missing_terms = [self._normalize_text(item) for item in search_context.get('missing_terms') or [] if self._normalize_text(item)]
        missing_aspects = [self._normalize_text(item) for item in search_context.get('missing_aspects') or [] if self._normalize_text(item)]
        violation_set = {self._normalize_text(item) for item in action_layer.do_not_claim if self._normalize_text(item)}
        response_text = self._normalize_text(user_response)

        if not response_text:
            return MeaningPreservationResult(
                preserved=False,
                severity='fail',
                recommended_action='block',
                violations=['empty_response'],
                safe_response=self._build_safe_response(search_context=search_context),
                reason='user response is empty after verbalization',
            )

        if need_search and attempted and search_error:
            return MeaningPreservationResult(
                preserved=False,
                severity='fail',
                recommended_action='replace',
                violations=['search_error_unresolved'],
                safe_response=self._build_safe_response(search_context=search_context),
                reason='search encountered an error so grounded free-form response should not pass through',
            )

        if need_search and attempted and no_evidence_found:
            return MeaningPreservationResult(
                preserved=False,
                severity='fail',
                recommended_action='replace',
                violations=['no_evidence_found'],
                safe_response=self._build_safe_response(search_context=search_context),
                reason='no external evidence was found for a response that required grounding',
            )

        if need_search and attempted and (missing_terms or missing_aspects):
            violations: list[str] = []
            if missing_terms:
                violations.append('missing_terms')
            if missing_aspects:
                violations.append('missing_aspects')
            return MeaningPreservationResult(
                preserved=False,
                severity='warn',
                recommended_action='replace',
                violations=violations,
                safe_response=self._build_safe_response(search_context=search_context),
                reason='grounding remains incomplete for required search slots',
            )

        if violation_set and not need_search:
            return MeaningPreservationResult(
                preserved=True,
                severity='ok',
                recommended_action='accept',
                violations=[],
                safe_response='',
                reason='no search-related preservation block triggered',
            )

        return MeaningPreservationResult(
            preserved=True,
            severity='ok',
            recommended_action='accept',
            violations=[],
            safe_response='',
            reason='response is within currently grounded bounds',
        )

    def _build_safe_response(self, *, search_context: dict[str, object]) -> str:
        missing_terms = [self._normalize_text(item) for item in search_context.get('missing_terms') or [] if self._normalize_text(item)]
        missing_aspects = [self._normalize_text(item) for item in search_context.get('missing_aspects') or [] if self._normalize_text(item)]
        search_error = self._normalize_text(search_context.get('error') or '')
        no_evidence_found = bool(search_context.get('no_evidence_found'))

        lines: list[str] = []
        if search_error:
            lines.append('외부 근거를 확인하는 과정에서 오류가 발생해, 지금은 확인된 범위를 넘는 답변을 만들지 않겠습니다.')
        elif no_evidence_found:
            lines.append('외부 검색을 시도했지만, 지금 질문을 뒷받침할 만큼 확인 가능한 근거를 찾지 못했습니다.')
        else:
            lines.append('현재 확보된 근거만으로는 질문에 필요한 내용을 충분히 확인하지 못했습니다.')

        if missing_terms:
            lines.append(f"아직 확인되지 않은 대상: {', '.join(missing_terms[:4])}.")
        if missing_aspects:
            lines.append(f"아직 확인되지 않은 측면: {', '.join(missing_aspects[:4])}.")
        lines.append('추정으로 빈칸을 메우지 않고, 확인된 정보만 기준으로 다시 답하겠습니다.')
        return ' '.join(lines).strip()

    def _normalize_text(self, value: object) -> str:
        return ' '.join(str(value or '').split()).strip()
