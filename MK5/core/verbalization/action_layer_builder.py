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

        response_mode = 'direct_answer_with_uncertainty'
        answer_goal = '현재 질문에 대해 확보된 범위만 답하고, 한계가 있으면 함께 밝힌다.'
        suggested_actions: list[str] = []
        do_not_claim = [
            '확보되지 않은 사실을 단정하지 않는다.',
            'debug나 내부 시스템 용어를 그대로 본문에 노출하지 않는다.',
            '내부 수치나 구조 상태를 사용자가 직접 묻지 않은 한 본문에 직접 나열하지 않는다.',
        ]
        tone_hint = 'natural_concise_korean'

        if intent == 'structure_review' or conflict_count > 0 or revision_count > 0:
            response_mode = 'structured_explanation'
            answer_goal = '현재 질문에 답하되, 판단에 불확실성이 있으면 보수적으로 함께 밝힌다.'
            suggested_actions = [
                '핵심 판단을 먼저 말한다.',
                '불확실성이 있으면 짧게 함께 밝힌다.',
            ]
        elif intent == 'relation_synthesis_request' or relation_count >= 2 or activated_count >= 3:
            response_mode = 'structured_explanation'
            answer_goal = '현재 질문에 대해 핵심 판단과 이유를 짧게 정리한다.'
            suggested_actions = [
                '핵심 판단을 먼저 말한다.',
                '필요하면 이유를 1~2문장 덧붙인다.',
            ]
        elif intent == 'memory_probe':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '현재 확보된 범위 안에서만 기억 여부를 신중하게 답한다.'
            suggested_actions = [
                '기억이 남아 있는 범위만 말한다.',
                '부족하면 부족하다고 분명히 말한다.',
            ]
        elif intent == 'open_information_request':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = '필요한 정보가 부족할 수 있음을 밝히고, 가능한 범위만 답한다.'
            suggested_actions = [
                '확보된 근거 범위만 답한다.',
                '부족한 경우 단정 대신 한계를 먼저 밝힌다.',
            ]

        if conclusion.detected_conflicts:
            do_not_claim.append('현재 충돌이 없다고 단정하지 않는다.')
        if not conclusion.activated_concepts:
            do_not_claim.append('아직 확보되지 않은 기억을 있는 것처럼 말하지 않는다.')

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
            },
        )
