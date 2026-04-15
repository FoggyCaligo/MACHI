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
        search_context = self._search_context(conclusion)

        response_mode = 'direct_answer_with_uncertainty'
        answer_goal = '사용자의 현재 질문에 바로 답한다. 모르면 추측 대신 모른다고 짧게 말한다.'
        suggested_actions: list[str] = [
            '첫 문장에서 질문의 핵심에 직접 답한다.',
            '질문을 다른 질문으로 바꾸지 않는다.',
        ]
        do_not_claim = [
            '확보되지 않은 사실을 단정하지 않는다.',
            'debug나 내부 시스템 용어를 그대로 본문에 노출하지 않는다.',
            '내부 수치나 구조 상태를 사용자가 직접 묻지 않은 한 본문에 직접 나열하지 않는다.',
            '답변 준비 상태나 계획만 보고하지 않는다.',
            '아직 실행되지 않은 행동을 미래형으로 약속하지 않는다.',
        ]
        tone_hint = 'natural_concise_korean'

        if search_context['attempted'] and search_context['result_count'] > 0:
            response_mode = 'search_grounded_answer'
            answer_goal = '이미 확보된 검색 자료를 바탕으로 사용자의 질문에 직접 답한다. 검색하겠다고 예고하지 않는다.'
            suggested_actions = [
                '첫 문장에서 검색으로 확인된 핵심 차이 또는 핵심 사실을 직접 말한다.',
                '필요하면 검색에서 확보된 근거를 짧게 덧붙인다.',
            ]
        elif search_context['attempted'] and search_context['result_count'] == 0:
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '검색을 시도했지만 자료를 확보하지 못했다면 그 사실을 짧게 밝히고, 남은 범위 안에서만 답한다.'
            suggested_actions = [
                '첫 문장에서 질문에 대해 지금 말할 수 있는 핵심만 답한다.',
                '검색 결과를 확보하지 못했다면 그 사실을 한 문장으로만 밝힌다.',
            ]
        elif intent == 'structure_review' or conflict_count > 0 or revision_count > 0:
            response_mode = 'structured_explanation'
            answer_goal = '사용자의 현재 질문에 답하되, 불확실한 부분은 짧게만 밝히고 내용 자체를 먼저 설명한다.'
            suggested_actions = [
                '첫 문장에서 핵심 판단을 말한다.',
                '불확실성은 필요할 때만 짧게 덧붙인다.',
            ]
        elif intent == 'relation_synthesis_request' or relation_count >= 2 or activated_count >= 3:
            response_mode = 'structured_explanation'
            answer_goal = '사용자의 질문에 대해 핵심 차이, 공통점, 이유 같은 내용을 바로 설명한다.'
            suggested_actions = [
                '핵심 내용을 먼저 말한다.',
                '이유나 비교 포인트를 1~2문장 덧붙인다.',
            ]
        elif intent == 'memory_probe':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '기억 여부를 직접 답한다. 기억이 없으면 없다고 바로 말한다.'
            suggested_actions = [
                '기억 여부를 첫 문장에서 답한다.',
                '부족하면 부족하다고 분명히 말한다.',
            ]
        elif intent == 'open_information_request':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '질문 자체에 직접 답한다. 정보가 부족해도 상태 보고만 하지 말고 가능한 핵심부터 말한다.'
            suggested_actions = [
                '질문의 핵심 내용을 먼저 답한다.',
                '한계가 있으면 두 번째 문장 이후에 짧게 덧붙인다.',
            ]

        if conclusion.detected_conflicts:
            do_not_claim.append('현재 충돌이 없다고 단정하지 않는다.')
        if not conclusion.activated_concepts:
            do_not_claim.append('아직 확보되지 않은 기억을 있는 것처럼 말하지 않는다.')
        if search_context['attempted']:
            do_not_claim.append('검색을 지금부터 하겠다고 예고하지 않는다.')

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
                'search_attempted': search_context['attempted'],
                'search_result_count': search_context['result_count'],
            },
        )

    def _search_context(self, conclusion: CoreConclusion) -> dict[str, int | bool]:
        raw = conclusion.metadata.get('search_context', {}) if conclusion.metadata else {}
        attempted = bool(raw.get('attempted')) if isinstance(raw, dict) else False
        result_count = int(raw.get('result_count', 0)) if isinstance(raw, dict) else 0
        return {'attempted': attempted, 'result_count': result_count}
