# Edge Family And Connect Type Design

Updated: 2026-04-16

## Core Shape
- `edge_family`: `concept` | `relation`
- `connect_type`: `flow` | `neutral` | `opposite` | `conflict`
- `relation_detail.kind`: fine-grained semantics (for example: `subtype_of`, `name_variant`, `creator_of`)

## Why This Split
- Keep high-level edge behavior stable (`family`, `type`).
- Keep detailed meaning flexible (`relation_detail.kind`).
- Allow multiple edges between the same node pair when semantics differ.

## Proposal Path For New Types
- If model proposes unknown `connect_type`, store edge with:
  - `connect_type=neutral`
  - `relation_detail.proposed_connect_type=<candidate>`
  - `relation_detail.proposal_reason=<reason>`
- Promote candidates to official type only after repeated evidence.

## Write-Back Paths
- `ModelFeedbackService`: adjusts support/conflict pressure on existing edges.
- `ModelEdgeAssertionService`: creates or reinforces structural edges from model assertions.

## Activation And Reasoning Impact
- Concept edges are prioritized in neighbor selection.
- Concept 2-hop expansion reduces hierarchy loss under edge budget.
- Contradiction/revision policy should consume `family/type/kind` together.

## Next Steps
1. Define promotion threshold for proposed connect types.
2. Add deterministic revision rules by `family/type/kind`.
3. Add tests for same-pair multi-edge coexistence.
