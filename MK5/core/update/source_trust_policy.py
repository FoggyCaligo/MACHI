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

    The world graph stays single-layered, but the initial trust and the trust
    growth rate vary by source_type and claim_domain.
    """

    def infer_claim_domain(self, text: str, *, source_type: str) -> str:
        lowered = (text or '').lower()
        if source_type == 'search':
            return 'world_fact'
        if source_type == 'assistant':
            if any(token in lowered for token in ('기억', '그래프', '현재 구조', '내가 아는 범위')):
                return 'graph_interpretation'
            return 'generated_answer'
        if any(token in lowered for token in ('나', '내', '내가', '기억', '취향', '원해', '싫어')):
            return 'user_state_or_preference'
        return 'general_claim'

    def profile_for(self, *, source_type: str, claim_domain: str | None = None) -> SourceTrustProfile:
        domain = claim_domain or 'general_claim'
        if source_type == 'user':
            if domain == 'user_state_or_preference':
                return SourceTrustProfile(source_type, domain, 0.72, 0.66, 0.050, 0.045, 0.28)
            return SourceTrustProfile(source_type, domain, 0.56, 0.58, 0.035, 0.025, 0.24)
        if source_type == 'assistant':
            if domain == 'graph_interpretation':
                return SourceTrustProfile(source_type, domain, 0.44, 0.42, 0.020, 0.015, 0.18)
            return SourceTrustProfile(source_type, domain, 0.32, 0.34, 0.012, 0.010, 0.14)
        if source_type == 'search':
            return SourceTrustProfile(source_type, domain, 0.46, 0.48, 0.028, 0.020, 0.22)
        if source_type == 'file':
            return SourceTrustProfile(source_type, domain, 0.60, 0.60, 0.030, 0.022, 0.24)
        return SourceTrustProfile(source_type or 'unknown', domain, 0.40, 0.40, 0.015, 0.010, 0.16)

    def clamp_trust(self, value: float) -> float:
        return max(0.0, min(1.0, round(value, 6)))
