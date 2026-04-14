from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SourceTrustProfile:
    source_type: str
    claim_domain: str
    initial_node_trust: float
    initial_edge_trust: float
    edge_support_trust_delta: float
    node_reuse_trust_delta: float
    edge_weight: float


class SourceTrustPolicy:
    """Trust policy for different evidence sources inside one world graph.

    Important constraint for early MK5:
    claim_domain inference must not depend on lexical keyword heuristics.
    Until a real intent/domain module exists, domains are derived from source
    provenance only, or from an explicit upstream override.
    """

    def infer_claim_domain(self, text: str, *, source_type: str) -> str:
        normalized_source = (source_type or 'unknown').strip().lower()
        if normalized_source == 'search':
            return 'world_fact'
        if normalized_source == 'assistant':
            return 'generated_answer'
        if normalized_source == 'file':
            return 'document_evidence'
        if normalized_source == 'user':
            return 'general_claim'
        return 'general_claim'

    def profile_for(self, *, source_type: str, claim_domain: str | None = None) -> SourceTrustProfile:
        domain = claim_domain or 'general_claim'
        if source_type == 'user':
            return SourceTrustProfile(source_type, domain, 0.56, 0.58, 0.035, 0.025, 0.24)
        if source_type == 'assistant':
            return SourceTrustProfile(source_type, domain, 0.32, 0.34, 0.012, 0.010, 0.14)
        if source_type == 'search':
            return SourceTrustProfile(source_type, domain, 0.46, 0.48, 0.028, 0.020, 0.22)
        if source_type == 'file':
            return SourceTrustProfile(source_type, domain, 0.60, 0.60, 0.030, 0.022, 0.24)
        return SourceTrustProfile(source_type or 'unknown', domain, 0.40, 0.40, 0.015, 0.010, 0.16)

    def clamp_trust(self, value: float) -> float:
        return max(0.0, min(1.0, round(value, 6)))
