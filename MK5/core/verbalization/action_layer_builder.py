from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion, DerivedActionLayer


@dataclass(slots=True)
class ActionLayerBuilder:
    def build(self, conclusion: CoreConclusion) -> DerivedActionLayer:
        relation_count = len(conclusion.key_relations)
        activated_count = len(conclusion.activated_concepts)
        conflict_count = len(conclusion.detected_conflicts)
        revision_count = len(conclusion.revision_decisions)
        intent = conclusion.inferred_intent
        search_context = conclusion.metadata.get('search_context', {}) if isinstance(conclusion.metadata, dict) else {}
        search_attempted = bool(search_context.get('attempted'))
        search_required = bool(search_context.get('need_search'))
        search_result_count = int(search_context.get('result_count') or 0)
        missing_terms = list(search_context.get('missing_terms') or [])
        missing_aspects = list(search_context.get('missing_aspects') or [])
        grounded_terms = list(search_context.get('grounded_terms') or [])
        search_error = search_context.get('error')
        no_evidence_found = bool(search_context.get('no_evidence_found'))

        response_mode = 'direct_answer_with_uncertainty'
        answer_goal = '현재 질문에 대해 확인된 정보 범위만 답하고, 빈칸은 추정으로 메우지 않는다.'
        suggested_actions: list[str] = []
        do_not_claim = [
            '확인되지 않은 사실을 단정하지 않는다.',
            'debug나 내부 시스템 용어를 사용자 답변에 그대로 노출하지 않는다.',
            '사용자가 직접 묻지 않은 내부 구조 상태를 본문에 직접 나열하지 않는다.',
        ]
        tone_hint = 'natural_concise_korean'

        if intent == 'structure_review' or conflict_count > 0 or revision_count > 0:
            response_mode = 'structured_explanation'
            answer_goal = '질문의 구조를 설명하되, 불확실한 부분은 보수적으로 한계를 밝힌다.'
            suggested_actions = [
                '비교 기준을 먼저 잡아 답한다.',
                '불확실한 부분은 짚어서 한계를 밝힌다.',
            ]
        elif intent == 'relation_synthesis_request' or relation_count >= 2 or activated_count >= 3:
            response_mode = 'structured_explanation'
            answer_goal = '질문과 직접 관련된 판단과 이유를 간결하게 정리한다.'
            suggested_actions = [
                '핵심 판단을 먼저 말한다.',
                '필요하면 이유를 1~2문장으로 덧붙인다.',
            ]
        elif intent == 'memory_probe':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '현재 정보 범위 안에서 기억 여부를 조심스럽게 답한다.'
            suggested_actions = [
                '기억이 있는 범위만 말한다.',
                '부족하면 부족하다고 분명히 말한다.',
            ]
        elif intent == 'open_information_request':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '필요한 정보가 부족하면 그 한계를 밝히고, 가능한 범위만 답한다.'
            suggested_actions = [
                '근거가 있는 범위만 답한다.',
                '부족한 경우 추정 대신 한계를 먼저 밝힌다.',
            ]

        if conclusion.detected_conflicts:
            do_not_claim.append('현재 충돌이 없다고 단정하지 않는다.')
        if not conclusion.activated_concepts:
            do_not_claim.append('아직 정보가 없는 내용을 기억이 있는 것처럼 말하지 않는다.')
        if search_error:
            do_not_claim.append('검색이 실패한 상태에서 확인되지 않은 사실을 메워 말하지 않는다.')
            suggested_actions.append('검색 실패로 확인되지 않은 내용은 모른다고 분명히 말한다.')
        if search_required and search_attempted and search_result_count == 0 and not search_error:
            response_mode = 'structured_explanation'
            answer_goal = '외부 검색이 필요했지만 확인 가능한 근거를 찾지 못했다는 점을 먼저 밝히고, 비어 있는 내용을 추정으로 메우지 않는다.'
            do_not_claim.append('외부 근거가 없는 상태에서 구조적 차이, 성능, 용도 차이를 사실처럼 단정하지 않는다.')
            suggested_actions.append('확인 가능한 외부 근거를 찾지 못했다는 점을 먼저 말한다.')
        if missing_terms:
            joined = ', '.join(missing_terms)
            do_not_claim.append(f'다음 항목에 대해서는 검색 근거 없이 세부 사실을 단정하지 않는다: {joined}')
            suggested_actions.append('확인된 항목과 아직 확인되지 않은 항목을 분리해서 말한다.')
        if missing_aspects:
            joined = ', '.join(missing_aspects)
            do_not_claim.append(f'다음 측면은 아직 외부 근거로 확인되지 않았으므로 단정하지 않는다: {joined}')
            suggested_actions.append('아직 확인되지 않은 측면은 추정하지 말고 한계로 남긴다.')
        if grounded_terms and missing_terms:
            answer_goal = '검색으로 확인된 항목은 요약하고, 확인되지 않은 항목은 단정하지 말고 한계를 밝힌다.'
        if no_evidence_found and not search_error:
            do_not_claim.append('검색 결과가 0건인 상태를 숨긴 채 이미 확인된 것처럼 말하지 않는다.')

        return DerivedActionLayer(
            response_mode=response_mode,
            answer_goal=answer_goal,
            suggested_actions=suggested_actions,
            do_not_claim=do_not_claim,
            tone_hint=tone_hint,
            metadata={
                'activated_concept_count': activated_count,
                'key_relation_count': relation_count,
                'conflict_count': conflict_count,
                'intent_basis': 'graph_state_only',
                'search_attempted': search_attempted,
                'search_required': search_required,
                'search_result_count': search_result_count,
                'no_evidence_found': no_evidence_found,
                'grounded_term_count': len(grounded_terms),
                'missing_term_count': len(missing_terms),
                'missing_aspect_count': len(missing_aspects),
            },
        )
