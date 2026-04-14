from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion, DerivedActionLayer


@dataclass(slots=True)
class ActionLayerBuilder:
    def build(self, conclusion: CoreConclusion) -> DerivedActionLayer:
        text = conclusion.user_input_summary
        inferred_intent = conclusion.inferred_intent
        lowered = text.lower()

        response_mode = 'direct_answer_with_uncertainty'
        answer_goal = '현재 그래프에 반영된 범위와 한계를 함께 설명한다.'
        suggested_actions: list[str] = []
        do_not_claim = [
            '그래프에 없는 사실을 단정하지 않는다.',
            'debug나 내부 용어를 그대로 본문에 노출하지 않는다.',
            '활성 노드 수, 엣지 수 같은 수치를 본문에 직접 나열하지 않는다.',
        ]
        tone_hint = 'natural_concise_korean'

        if '기억' in text:
            response_mode = 'memory_answer_with_scope'
            answer_goal = '현재 그래프에 실제로 남아 있는 범위 안에서만 기억 여부를 답한다.'
            suggested_actions = [
                '기억하고 있는 범위만 짧게 말한다.',
                '기억이 부족하면 부족하다고 분명히 말한다.',
            ]
        elif any(token in text for token in ('설명', '정리', '역할', '무엇', '왜')) or inferred_intent == 'explanation_request':
            response_mode = 'structured_explanation'
            answer_goal = '핵심 판단을 먼저 말하고 필요한 이유를 짧게 덧붙인다.'
            suggested_actions = [
                '핵심 판단을 먼저 말한다.',
                '필요하면 이유를 1~2문장 덧붙인다.',
            ]
        elif any(token in text for token in ('수정', '구현', '진행', '만들', '붙여')) or inferred_intent == 'implementation_or_change_request':
            response_mode = 'implementation_guidance'
            answer_goal = '지금 해야 할 다음 작업 또는 수정 방향을 짧게 제안한다.'
            suggested_actions = [
                '현재 가장 우선순위가 높은 작업을 말한다.',
                '필요하면 다음 수정 대상을 한두 개 제안한다.',
            ]
        elif any(token in lowered for token in ('안녕', 'hello', 'hi')):
            response_mode = 'light_social_with_scope'
            answer_goal = '짧고 자연스럽게 응답하되, 기억 여부처럼 추가 질문이 있으면 그 범위만 답한다.'
            suggested_actions = [
                '인사는 짧고 자연스럽게 한다.',
                '추가 질문이 있으면 그래프에 근거한 범위만 이어서 답한다.',
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
                'activated_concept_count': len(conclusion.activated_concepts),
                'key_relation_count': len(conclusion.key_relations),
                'conflict_count': len(conclusion.detected_conflicts),
            },
        )
