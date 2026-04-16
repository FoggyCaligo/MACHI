# Identity And Temporal Design

Updated: 2026-04-16

## Goal
Keep identity continuity and topic continuity in the graph layer, not prompt-only behavior.

## Identity Modeling
- Represent entities as nodes.
- Keep hierarchy with `concept/flow` edges.
- Keep naming/alias links with `concept/neutral` edges.
- Keep interaction state with `relation/*` edges.

## Temporal Handling
- Do not create a new subtype node for every time slice.
- Track changes through Node/Edge timestamps and event lineage.
- Use history traversal to answer "past vs current state" queries.

## Activation Requirements
- Identity anchors must be visible in local thought view.
- Concept hierarchy must survive edge budget limits.
- Concept 2-hop expansion is required for better continuity.

## Current Implementation Notes
- Session identity anchors are introduced in ingest/activation path.
- `ActivationEngine` includes concept-priority sorting and concept 2-hop expansion.
- Debug metadata includes identity and concept-hop signals.

## Next Steps
1. Strengthen identity-specific contradiction/revision rules.
2. Add explicit as-of traversal contract.
3. Add regression tests for name continuity and self/other distinction.
