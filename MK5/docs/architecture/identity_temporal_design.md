# Identity And Temporal Design

Updated: 2026-04-16

## Goal
Keep identity continuity and temporal continuity in the graph layer, not prompt-only behavior.

## Identity Modeling
- Entities are represented as nodes.
- Hierarchy is read through `concept/flow` edges.
- Naming/alias/display variants are read through `concept/neutral` edges.
- Interaction state is read through `relation/*` edges.
- Identity should not depend on string hard-coding or prompt-only persistence.

## Pronoun And Session Overlay
- Pronouns like `나`, `너` are not treated as permanent hard-coded identity nodes.
- Session-specific references may be represented as temporary bindings on top of long-lived graph nodes.
- The long-lived graph keeps stable identity anchors; the current conversation can overlay temporary reference edges when needed.

## Temporal Handling
- Do not create a new subtype node for every time slice.
- Keep the same node/edge, accumulate updates, and use event history for reconstruction.
- When past state is needed, reconstruct a past **local active graph** from the current node/edge and bounded logs.

## Activation Requirements
- Identity anchors must be visible in the local thought view when relevant.
- Concept hierarchy must survive edge budget limits.
- The graph should support both local activation reasoning and direct node access.

## Current Direction
- Session identity anchors may exist, but they should not become a prompt-only substitute for graph structure.
- `concept/flow`, `concept/neutral`, `relation/*` should remain readable from graph structure itself.
- Temporary bindings should be cleared when they are no longer contextually active.

## Next Steps
1. Strengthen identity-specific contradiction/revision rules using graph structure, not string labels.
2. Define the explicit direct-access + local-activation contract.
3. Define the bounded-log based temporal reconstruction contract.
