from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion, DerivedActionLayer


@dataclass(slots=True)
class TemplateVerbalizer:
    max_conflicts: int = 3
    max_revisions: int = 3

    def build_user_response(self, conclusion: CoreConclusion, action_layer: DerivedActionLayer) -> str:
        if action_layer.response_mode == 'memory_answer_with_scope':
            if conclusion.activated_concepts:
                return '지금 그래프에 반영된 범위에서는 네 대화 흔적이 일부 남아 있어. 다만 아직 내용을 그대로 말할 만큼 충분히 정리된 기억 구조라고 보긴 어려워.'
            return '아직 그래프에 남아 있다고 말할 만한 기억은 충분하지 않아.'

        if action_layer.response_mode == 'light_social_with_scope':
            return '안녕하세요. 지금은 그래프에 반영된 범위를 바탕으로만 답하고 있어.'

        if action_layer.response_mode == 'structured_explanation':
            if conclusion.detected_conflicts:
                return '핵심 판단부터 말하면, 현재 구조에는 추가 점검이 필요한 충돌이 있어. 그래서 지금은 보수적으로 설명하는 편이 맞아.'
            return '핵심 판단부터 말하면, 현재 구조에서는 즉시 수정이 필요한 충돌은 아직 보이지 않아.'

        if action_layer.response_mode == 'implementation_guidance':
            if conclusion.revision_decisions:
                return '지금은 구조 수정 후보가 일부 보였어. 우선 그 지점부터 정리하면서 다음 수정 대상을 좁혀가는 게 맞아.'
            return '지금은 큰 구조를 유지한 채 다음 구현 단계로 넘어가도 되는 상태야.'

        if conclusion.detected_conflicts:
            return '지금 입력은 반영됐고, 현재 구조에는 추가 점검이 필요한 충돌이 일부 보여.'
        return '지금 입력은 반영됐고, 현재 구조에서는 즉시 수정이 필요한 충돌은 아직 보이지 않아.'

    def build_internal_explanation(self, conclusion: CoreConclusion) -> str:
        lines: list[str] = []
        lines.append(conclusion.explanation_summary)
        lines.append('')
        lines.append(f"- 해석된 의도: {conclusion.inferred_intent}")
        lines.append(f"- 활성 개념 노드 수: {len(conclusion.activated_concepts)}")
        lines.append(f"- 핵심 관계 참조 수: {len(conclusion.key_relations)}")

        if conclusion.detected_conflicts:
            lines.append('')
            lines.append('감지된 구조 충돌:')
            for item in conclusion.detected_conflicts[: self.max_conflicts]:
                lines.append(
                    f"- edge#{item.edge_id} [{item.edge_type}] {item.reason} | severity={item.severity} | score={item.score:.2f}"
                )
        else:
            lines.append('')
            lines.append('감지된 구조 충돌은 아직 없다.')

        if conclusion.revision_decisions:
            lines.append('')
            lines.append('이번 사이클의 구조 판단:')
            for item in conclusion.revision_decisions[: self.max_revisions]:
                state = '비활성화' if item.deactivated else item.action
                lines.append(
                    f"- edge#{item.edge_id}: {state} | reason={item.reason} | trust {item.before_trust:.2f}->{item.after_trust:.2f}"
                )
        elif conclusion.trust_changes:
            lines.append('')
            lines.append('이번 사이클에서는 신뢰도 변화만 기록되고 구조 교체는 보류되었다.')
        else:
            lines.append('')
            lines.append('이번 사이클에서는 구조 보존이 유지되었다.')

        return '\n'.join(lines).strip()
