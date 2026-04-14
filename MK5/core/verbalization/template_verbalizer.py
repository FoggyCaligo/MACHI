from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion


@dataclass(slots=True)
class TemplateVerbalizer:
    max_conflicts: int = 3
    max_revisions: int = 3

    def verbalize(self, conclusion: CoreConclusion) -> str:
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
