from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.entities.graph_event import GraphEvent
from core.entities.intent import IntentSnapshot
from core.entities.thought_view import ThoughtView
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class IntentManager:
    drive_name: str = 'user_delight'
    history_limit: int = 24
    shift_margin: float = 0.14
    base_stop_threshold: float = 0.62

    def resolve(
        self,
        uow: UnitOfWork,
        *,
        request,
        thought_view: ThoughtView,
        contradiction_signals: list,
        trust_updates: list,
        revision_actions: list,
    ) -> IntentSnapshot:
        recent_messages = list(uow.chat_messages.list_by_session(request.session_id, limit=self.history_limit))
        previous_snapshot_meta = self._latest_snapshot_metadata(recent_messages)
        features = self._collect_features(
            thought_view=thought_view,
            contradiction_signals=contradiction_signals,
            trust_updates=trust_updates,
            revision_actions=revision_actions,
            previous_snapshot_meta=previous_snapshot_meta,
        )
        scores = self._score_candidates(features)
        previous_name = self._previous_intent_name(previous_snapshot_meta)
        current_name, shifted, shift_reason = self._choose_snapshot_intent(
            scores=scores,
            previous_name=previous_name,
            features=features,
        )
        continuation = bool(previous_name and current_name == previous_name and not shifted)
        sufficiency_score = self._compute_sufficiency_score(features, scores[current_name], continuation=continuation)
        stop_threshold = self._compute_stop_threshold(features, previous_snapshot_meta)
        should_stop = self._should_stop(
            intent_name=current_name,
            features=features,
            sufficiency_score=sufficiency_score,
            stop_threshold=stop_threshold,
        )
        evidence = self._build_evidence(
            intent_name=current_name,
            features=features,
            previous_name=previous_name,
            shifted=shifted,
        )

        snapshot = IntentSnapshot(
            drive_name=self.drive_name,
            live_intent=current_name,
            snapshot_intent=current_name,
            previous_snapshot_intent=previous_name,
            shifted=shifted,
            continuation=continuation,
            shift_reason=shift_reason,
            sufficiency_score=sufficiency_score,
            stop_threshold=stop_threshold,
            should_stop=should_stop,
            evidence=evidence,
            metadata={
                'candidate_scores': {key: round(value, 6) for key, value in scores.items()},
                'features': self._serialize_features(features),
            },
        )
        self._record_snapshot_event(uow, request=request, snapshot=snapshot)
        return snapshot

    def _latest_snapshot_metadata(self, messages: list) -> dict[str, Any] | None:
        for message in reversed(messages):
            if getattr(message, 'role', None) != 'assistant':
                continue
            metadata = getattr(message, 'metadata', {}) or {}
            snapshot = metadata.get('intent_snapshot')
            if isinstance(snapshot, dict) and snapshot.get('snapshot_intent'):
                return snapshot
        return None

    def _previous_intent_name(self, snapshot_metadata: dict[str, Any] | None) -> str | None:
        if not snapshot_metadata:
            return None
        name = snapshot_metadata.get('snapshot_intent')
        return str(name) if isinstance(name, str) and name else None

    def _collect_features(
        self,
        *,
        thought_view: ThoughtView,
        contradiction_signals: list,
        trust_updates: list,
        revision_actions: list,
        previous_snapshot_meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        inquiry_count = sum(1 for block in thought_view.seed_blocks if block.block_kind == 'inquiry_phrase')
        relation_phrase_count = sum(1 for block in thought_view.seed_blocks if block.block_kind == 'relation_phrase')
        statement_count = sum(1 for block in thought_view.seed_blocks if block.block_kind == 'statement_phrase')
        pattern_count = len(thought_view.activated_patterns)
        seed_count = len(thought_view.seed_nodes)
        local_node_count = len(thought_view.nodes)
        edge_count = len(thought_view.edges)
        pointer_count = len(thought_view.pointers)
        contradiction_count = len(contradiction_signals)
        trust_update_count = len(trust_updates)
        revision_count = len(revision_actions)
        deactivated_count = sum(1 for item in revision_actions if getattr(item, 'deactivated', False))
        graph_sparse = seed_count <= 2 and edge_count <= 1
        graph_dense = edge_count >= max(4, seed_count)
        pattern_rich = pattern_count > 0
        pointer_backed = pointer_count > 0
        previous_activated = set(previous_snapshot_meta.get('metadata', {}).get('activated_concepts', []) or []) if previous_snapshot_meta else set()
        current_activated = [node.id for node in thought_view.nodes if node.id is not None]
        current_seed_ids = [item.node.id for item in thought_view.seed_nodes if item.node.id is not None]
        overlap_count = len(previous_activated.intersection(current_seed_ids)) if previous_activated else 0

        return {
            'inquiry_count': inquiry_count,
            'relation_phrase_count': relation_phrase_count,
            'statement_count': statement_count,
            'pattern_count': pattern_count,
            'seed_count': seed_count,
            'local_node_count': local_node_count,
            'edge_count': edge_count,
            'pointer_count': pointer_count,
            'contradiction_count': contradiction_count,
            'trust_update_count': trust_update_count,
            'revision_count': revision_count,
            'deactivated_count': deactivated_count,
            'graph_sparse': graph_sparse,
            'graph_dense': graph_dense,
            'pattern_rich': pattern_rich,
            'pointer_backed': pointer_backed,
            'overlap_count': overlap_count,
            'current_activated': current_activated,
            'current_seed_ids': current_seed_ids,
            'previous_snapshot_meta': previous_snapshot_meta or {},
        }

    def _score_candidates(self, features: dict[str, Any]) -> dict[str, float]:
        scores = {
            'structure_review': 0.05,
            'memory_probe': 0.05,
            'open_information_request': 0.05,
            'relation_synthesis_request': 0.05,
            'graph_grounded_reasoning': 0.10,
        }

        if features['contradiction_count'] or features['revision_count'] or features['deactivated_count']:
            scores['structure_review'] += 0.72
            scores['graph_grounded_reasoning'] -= 0.05
        scores['structure_review'] += min(features['trust_update_count'] * 0.08, 0.16)

        if features['inquiry_count']:
            scores['open_information_request'] += 0.42
        if features['graph_sparse']:
            scores['open_information_request'] += 0.16
        if features['inquiry_count'] and features['graph_dense']:
            scores['relation_synthesis_request'] += 0.12

        if features['pointer_backed'] and features['graph_sparse']:
            scores['memory_probe'] += 0.42
        if features['overlap_count'] > 0:
            scores['memory_probe'] += min(features['overlap_count'] * 0.08, 0.16)

        if features['relation_phrase_count']:
            scores['relation_synthesis_request'] += 0.28
        if features['pattern_rich']:
            scores['relation_synthesis_request'] += 0.24
        if features['graph_dense']:
            scores['relation_synthesis_request'] += 0.16

        if features['local_node_count'] > 0:
            scores['graph_grounded_reasoning'] += 0.18
        if features['edge_count'] > 0:
            scores['graph_grounded_reasoning'] += 0.14
        if not features['inquiry_count'] and not features['contradiction_count']:
            scores['graph_grounded_reasoning'] += 0.06

        previous_name = self._previous_intent_name(features['previous_snapshot_meta'])
        if previous_name in scores and features['overlap_count'] > 0 and not features['contradiction_count']:
            scores[previous_name] += 0.12
        return scores

    def _choose_snapshot_intent(
        self,
        *,
        scores: dict[str, float],
        previous_name: str | None,
        features: dict[str, Any],
    ) -> tuple[str, bool, str | None]:
        ordered = sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        best_name, best_score = ordered[0]
        if previous_name is None or previous_name not in scores:
            return best_name, False, None

        previous_score = scores[previous_name]
        if self._requires_forced_shift(best_name, previous_name, features):
            return best_name, best_name != previous_name, 'contradiction_or_revision_forced_shift'

        if best_name != previous_name and best_score >= previous_score + self.shift_margin:
            return best_name, True, f'score_shift:{previous_name}->{best_name}'

        if features['overlap_count'] > 0 and not features['contradiction_count'] and not features['revision_count']:
            return previous_name, False, None
        return best_name, False, None

    def _requires_forced_shift(self, best_name: str, previous_name: str, features: dict[str, Any]) -> bool:
        if features['contradiction_count'] or features['revision_count'] or features['deactivated_count']:
            return best_name == 'structure_review' and previous_name != 'structure_review'
        return False

    def _compute_sufficiency_score(self, features: dict[str, Any], chosen_score: float, *, continuation: bool) -> float:
        score = 0.12
        score += min(features['seed_count'], 4) * 0.06
        score += min(features['edge_count'], 6) * 0.05
        score += min(features['pattern_count'], 3) * 0.06
        score += min(features['overlap_count'], 2) * 0.05
        if continuation:
            score += 0.06
        if features['pointer_backed'] and features['graph_sparse']:
            score += 0.05
        if features['contradiction_count']:
            score -= 0.22
        if features['revision_count']:
            score -= 0.16
        if features['graph_sparse'] and features['inquiry_count']:
            score -= 0.08
        score += min(chosen_score * 0.18, 0.18)
        return round(max(0.0, min(1.0, score)), 6)

    def _compute_stop_threshold(self, features: dict[str, Any], previous_snapshot_meta: dict[str, Any] | None) -> float:
        threshold = self.base_stop_threshold
        if features['contradiction_count'] or features['revision_count']:
            threshold += 0.12
        if features['graph_sparse'] and features['inquiry_count']:
            threshold += 0.05
        if previous_snapshot_meta:
            previous_shifted = bool(previous_snapshot_meta.get('shifted'))
            previous_sufficiency = float(previous_snapshot_meta.get('sufficiency_score', 0.0) or 0.0)
            if previous_shifted:
                threshold += 0.04
            if previous_sufficiency < 0.45:
                threshold += 0.03
        return round(max(0.45, min(0.9, threshold)), 6)

    def _should_stop(
        self,
        *,
        intent_name: str,
        features: dict[str, Any],
        sufficiency_score: float,
        stop_threshold: float,
    ) -> bool:
        if intent_name == 'structure_review':
            return features['contradiction_count'] == 0 and sufficiency_score >= stop_threshold
        if intent_name == 'open_information_request':
            return not features['graph_sparse'] and sufficiency_score >= stop_threshold
        return sufficiency_score >= stop_threshold

    def _build_evidence(
        self,
        *,
        intent_name: str,
        features: dict[str, Any],
        previous_name: str | None,
        shifted: bool,
    ) -> list[str]:
        evidence: list[str] = []
        if features['contradiction_count']:
            evidence.append(f"contradictions:{features['contradiction_count']}")
        if features['revision_count']:
            evidence.append(f"revisions:{features['revision_count']}")
        if features['inquiry_count']:
            evidence.append(f"inquiry_blocks:{features['inquiry_count']}")
        if features['relation_phrase_count']:
            evidence.append(f"relation_blocks:{features['relation_phrase_count']}")
        if features['pattern_count']:
            evidence.append(f"patterns:{features['pattern_count']}")
        if features['pointer_count']:
            evidence.append(f"pointers:{features['pointer_count']}")
        if features['overlap_count']:
            evidence.append(f"overlap_with_previous:{features['overlap_count']}")
        if previous_name:
            evidence.append(f"previous_snapshot:{previous_name}")
        if shifted:
            evidence.append(f"shifted_to:{intent_name}")
        if not evidence:
            evidence.append('default_graph_grounded_reasoning')
        return evidence

    def _serialize_features(self, features: dict[str, Any]) -> dict[str, Any]:
        serialized = {key: value for key, value in features.items() if key != 'previous_snapshot_meta'}
        previous_meta = features.get('previous_snapshot_meta') or {}
        if previous_meta:
            serialized['previous_snapshot_intent'] = previous_meta.get('snapshot_intent')
            serialized['previous_shifted'] = previous_meta.get('shifted')
        return serialized

    def _record_snapshot_event(self, uow: UnitOfWork, *, request, snapshot: IntentSnapshot) -> None:
        uow.graph_events.add(
            GraphEvent(
                event_uid=f'evt_{uuid4().hex}',
                event_type='intent_snapshot_decided',
                message_id=request.message_id,
                input_text=request.message_text,
                parsed_input={'session_id': request.session_id},
                effect=snapshot.to_metadata(),
                note='Intent snapshot resolved from graph state and recent session continuity.',
            )
        )
