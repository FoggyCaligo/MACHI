# ConceptMerge

Created: 2026-04-23  
Updated: 2026-08-01  
Status: implemented in `core/thinking/concept_merge.py`

## Role

`ConceptMerge` prevents long-term graph fragmentation by merging only concept pairs that
have become strong enough to be treated as the same concept.

It is intentionally more conservative than `ConceptDifferentiation`.

## Current policy

Merge is allowed only when all of the following hold:

- similarity score is at least `0.985`
- both nodes are stable enough
- both nodes share enough structural neighbors
- direct support between the pair has accumulated enough evidence
- two brand-new nodes are not merged immediately in the same fresh state

## Similarity

The merge score uses the same composite scoring family as differentiation:

- embedding cosine similarity
- neighborhood overlap

During merge scoring, the candidate pair itself is excluded from each other's neighbor set.
This avoids a support edge or alias-evidence edge artificially lowering the structural score.

## Delayed alias-merge flow

`MK6_1` now uses a delayed merge path instead of immediate same-node attachment.

1. separate surface forms can exist as separate nodes first
2. `surface_variant_evidence` adds or strengthens a persistent edge between likely aliases
3. `concept_merge` reads that accumulated evidence later
4. only then can the two nodes merge

This keeps early interpretation flexible and avoids over-eager collapse.

## `surface_variant_evidence`

Alias evidence is language-neutral. It does not depend on hard-coded string heuristics.

Current evidence sources:

- embedding similarity
- shared structural neighborhood

The evidence edge stores payload such as:

- `alias_evidence`
- `evidence_types`
- `composite_score`
- `shared_neighbor_count`
- `observation_count`
- `alias_confidence`

When the same pair is re-observed, the edge is updated instead of duplicated:

- `support_count` increases
- `observation_count` increases
- confidence and weight can grow conservatively

## Incremental re-checking

Merge checking is incremental.

- previously checked pairs are usually skipped
- but if a related edge is newly added or updated, the touched pair is reconsidered

This matters for alias evidence:

- a pair may have been checked before
- later, `surface_variant_evidence` can add or strengthen support
- `concept_merge` should then re-evaluate that pair without needing a full reset

## Support accounting

Support is not just "any edge count".

- normal persistent pair edges contribute by `support_count`
- `surface_variant_evidence` contributes through a conservative support interpretation based on:
  - observation count
  - shared-neighbor count
  - alias confidence

This lets repeated language-neutral evidence matter without relying on any name-specific rule.

## Execution point

`ConceptMerge` runs in the update loop after structural evidence has been added.

In practice it complements:

- `ConceptDifferentiation`
- search-result ingestion
- alias-evidence accumulation

## Outcome

When a merge happens:

1. a survivor node is chosen by stability
2. the deprecated node's edges are rewired to the survivor
3. the deprecated node is removed from the temporary graph
4. merge mappings are recorded for later commit handling

## Design intent

The intended behavior is:

- do not force two forms into one node immediately
- allow separate concepts to stay separate early
- merge only after the graph itself has accumulated enough evidence

That matches the "separate first, merge later" direction for synonym / alias handling.
