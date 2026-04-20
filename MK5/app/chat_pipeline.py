from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config import REVISION_RULE_OVERRIDES_PATH, REVISION_RULE_OVERRIDES_STRICT, REVISION_RULE_PROFILE
from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.entities.conclusion_view import ConclusionView
from core.search.search_sidecar import SearchEvidence, SearchRunResult, SearchSidecar
from core.thinking.conclusion_view_builder import ConclusionViewBuilder
from core.thinking.structure_revision_service import StructureRevisionService
from core.thinking.thought_engine import ThoughtEngine, ThoughtRequest
from core.update.connect_type_promotion_service import ConnectTypePromotionResult, ConnectTypePromotionService
from core.update.graph_commit_service import GraphCommitService
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestResult, GraphIngestService
from core.update.model_edge_assertion_service import ModelEdgeAssertionResult, ModelEdgeAssertionService
from core.update.node_merge_service import NodeMergeService
from core.update.temporary_edge_service import TemporaryEdgeCleanupResult, TemporaryEdgeService
from core.verbalization.verbalizer import Verbalizer
from storage.sqlite.unit_of_work import SqliteUnitOfWork


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / 'data' / 'memory.db'
SCHEMA_PATH = PROJECT_ROOT / 'storage' / 'schema.sql'
DEFAULT_MODEL_NAME = 'mk5-graph-core'
SEARCH_MODEL_SELECTION_REQUIRED_ERROR = 'question slot planner requires a selectable LLM model'
_THINK_SEARCH_MAX_LOOPS = 3  # Think → Search 루프 최대 반복 횟수


class UserFacingChatError(RuntimeError):
    """Raised for actionable chat errors that should be shown directly to the user."""


@dataclass(slots=True)
class ChatPipelineRequest:
    session_id: str
    message: str
    turn_index: int
    attached_files: list[dict[str, Any]] | None = None
    model_name: str = DEFAULT_MODEL_NAME


class ChatPipeline:
    def __init__(
        self,
        db_path: Path = DB_PATH,
        schema_path: Path = SCHEMA_PATH,
        *,
        verbalizer: Verbalizer | None = None,
        search_sidecar: SearchSidecar | None = None,
        model_edge_assertion_service: ModelEdgeAssertionService | None = None,
        connect_type_promotion_service: ConnectTypePromotionService | None = None,
        graph_commit_service: GraphCommitService | None = None,
        temporary_edge_service: TemporaryEdgeService | None = None,
        revision_rule_overrides_path: str | Path | None = None,
        revision_rule_profile: str = REVISION_RULE_PROFILE,
        revision_rule_overrides_strict: bool = REVISION_RULE_OVERRIDES_STRICT,
    ) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        (
            self.revision_rule_overrides,
            self.revision_rule_override_path,
            self.revision_rule_override_load_error,
        ) = self._load_revision_rule_overrides(
            revision_rule_overrides_path
            if revision_rule_overrides_path is not None
            else REVISION_RULE_OVERRIDES_PATH,
            strict=revision_rule_overrides_strict,
        )
        self.revision_rule_profile = revision_rule_profile or ''
        self.ingest_service = GraphIngestService(self._uow_factory)
        self.activation_engine = ActivationEngine(self._uow_factory)
        self.thought_engine = ThoughtEngine(
            self._uow_factory,
            structure_revision_service=StructureRevisionService(
                node_merge_service=NodeMergeService(self._uow_factory),
                rule_overrides=self.revision_rule_overrides,
            ),
        )
        self.verbalizer = verbalizer or Verbalizer()
        self.conclusion_view_builder = ConclusionViewBuilder()
        self.search_sidecar = search_sidecar or SearchSidecar()
        self.model_edge_assertion_service = model_edge_assertion_service or ModelEdgeAssertionService(self._uow_factory)
        self.connect_type_promotion_service = connect_type_promotion_service or ConnectTypePromotionService()
        self.graph_commit_service = graph_commit_service or GraphCommitService(self._uow_factory)
        self.temporary_edge_service = temporary_edge_service or TemporaryEdgeService()

    def _uow_factory(self) -> SqliteUnitOfWork:
        return SqliteUnitOfWork(self.db_path, schema_path=self.schema_path, initialize_schema=True)

    def process(self, request: ChatPipelineRequest) -> dict[str, Any]:
        attached_files = request.attached_files or []
        user_claim_domain = self.ingest_service.trust_policy.infer_claim_domain(request.message, source_type='user')
        ingest_result = self.ingest_service.ingest(
            GraphIngestRequest(
                session_id=request.session_id,
                turn_index=request.turn_index,
                role='user',
                content=request.message,
                attached_files=attached_files,
                metadata={'source': 'ui_chat'},
                source_type='user',
                claim_domain=user_claim_domain,
            )
        )

        thought_view = self.activation_engine.build_view(
            ActivationRequest(
                session_id=request.session_id,
                content=request.message,
            )
        )
        # ── Think → Search 루프 (최대 _THINK_SEARCH_MAX_LOOPS 회) ──────────────────
        # 매 회차: Think → 검색 필요 없으면 break → 검색 결과 Ingest → Re-Activation → 반복
        # for-else: break 없이 최대 횟수 도달 시 마지막 enriched 뷰로 최종 Think 1회 추가
        search_run: SearchRunResult | None = None
        all_search_results: list[SearchEvidence] = []
        search_ingest_results: list[GraphIngestResult] = []

        for _loop_index in range(_THINK_SEARCH_MAX_LOOPS):
            thought_result = self.thought_engine.think(
                ThoughtRequest(
                    session_id=request.session_id,
                    message_id=ingest_result.message_id,
                    message_text=request.message,
                ),
                thought_view,
            )
            if thought_result.core_conclusion is None:
                raise RuntimeError('ThoughtEngine did not produce core_conclusion')

            search_run = self.search_sidecar.run(
                message=request.message,
                thought_view=thought_view,
                conclusion=thought_result.core_conclusion,
                model_name=request.model_name,
            )
            self._raise_if_search_requires_model_selection(request=request, search_run=search_run)

            if not search_run.results:
                # 검색 결과 없음(또는 검색 불필요) → 현재 thought_result가 최종
                break

            # 검색 결과 Ingest
            for index, item in enumerate(search_run.results, start=len(all_search_results) + 1):
                search_ingest_results.append(
                    self.ingest_service.ingest(
                        GraphIngestRequest(
                            session_id=request.session_id,
                            turn_index=request.turn_index,
                            role='search',
                            content=item.text_for_graph,
                            metadata={
                                'source': item.provider,
                                'url': item.url,
                                'title': item.title,
                                'search_rank': index,
                                'planned_query': item.metadata.get('planned_query'),
                            },
                            source_type='search',
                            claim_domain=item.claim_domain,
                        )
                    )
                )
            all_search_results.extend(search_run.results)

            # Re-Activation: 다음 Think를 위해 enriched 그래프 상태로 뷰 재구성
            thought_view = self.activation_engine.build_view(
                ActivationRequest(
                    session_id=request.session_id,
                    content=request.message,
                )
            )

        else:
            # for-else: break 없이 최대 횟수(_THINK_SEARCH_MAX_LOOPS) 도달
            # → 마지막 검색 결과가 반영된 뷰로 최종 Think 1회 추가 실행
            thought_result = self.thought_engine.think(
                ThoughtRequest(
                    session_id=request.session_id,
                    message_id=ingest_result.message_id,
                    message_text=request.message,
                ),
                thought_view,
            )
            if thought_result.core_conclusion is None:
                raise RuntimeError('ThoughtEngine did not produce core_conclusion after max search loops')

        if search_run is None:  # defensive: _THINK_SEARCH_MAX_LOOPS > 0 이므로 실제 불가
            raise RuntimeError('Think-Search loop produced no search run')

        intent_snapshot_meta = dict(thought_result.metadata.get('intent_snapshot', {}) or {})
        temporary_edge_cleanup_result: TemporaryEdgeCleanupResult = self.temporary_edge_service.cleanup_on_topic_shift(
            self._uow_factory,
            session_id=request.session_id,
            current_turn_index=request.turn_index,
            intent_snapshot=intent_snapshot_meta,
        )
        if temporary_edge_cleanup_result.triggered and temporary_edge_cleanup_result.deactivated_edge_ids:
            # Temporary edge cleanup happens after we already built the first thought view.
            # Rebuild once so the current-turn answer is generated from the cleaned graph state.
            thought_view = self.activation_engine.build_view(
                ActivationRequest(
                    session_id=request.session_id,
                    content=request.message,
                )
            )
            thought_result = self.thought_engine.think(
                ThoughtRequest(
                    session_id=request.session_id,
                    message_id=ingest_result.message_id,
                    message_text=request.message,
                ),
                thought_view,
            )
            if thought_result.core_conclusion is None:
                raise RuntimeError('ThoughtEngine did not produce core_conclusion after temporary edge cleanup')

        model_edge_assertion_result: ModelEdgeAssertionResult = self.model_edge_assertion_service.assert_edges(
            model_name=request.model_name,
            message=request.message,
            thought_view=thought_view,
        )
        connect_type_promotion_result: ConnectTypePromotionResult
        with self._uow_factory() as uow:
            connect_type_promotion_result = self.connect_type_promotion_service.promote(
                uow,
                message_id=ingest_result.message_id,
            )
            uow.commit()

        # ── ConclusionView 구성: Think→Search 루프의 최종 결과물을 의도 키워드 기반으로 선별 ──
        # CoreConclusion은 루프 내부 전용 중간 산물로 남고,
        # ConclusionView가 Verbalization 계층이 참조하는 유일한 결론 구조다.
        conclusion_view = self.conclusion_view_builder.build(
            request=ThoughtRequest(
                session_id=request.session_id,
                message_id=ingest_result.message_id,
                message_text=request.message,
            ),
            thought_view=thought_view,
            thought_result=thought_result,
        )

        self._attach_search_context(conclusion_view, search_run=search_run)

        verbalized = self.verbalizer.verbalize(conclusion_view, model_name=request.model_name)
        if verbalized.llm_error or not verbalized.user_response:
            if verbalized.llm_error and verbalized.llm_error.startswith('template_verbalizer_disabled:'):
                raise RuntimeError(
                    '현재 응답을 생성할 수 있는 모델이 없습니다. 모델을 선택하거나 OLLAMA 환경을 확인해주세요.'
                )
            if verbalized.llm_error_code == 'timeout':
                raise UserFacingChatError(
                    '선택한 모델의 응답 생성이 제한 시간 안에 끝나지 않았습니다. 더 빠른 모델로 바꾸거나, Ollama 상태와 모델 로드 상태를 확인한 뒤 다시 시도해주세요.'
                )
            raise RuntimeError(
                f"Verbalization failed: {verbalized.llm_error or 'empty response from verbalizer'}"
            )

        thought_result.derived_action = verbalized.derived_action
        intent_snapshot_metadata = dict(thought_result.metadata.get('intent_snapshot', {}) or {})
        if verbalized.derived_action is not None:
            intent_snapshot_metadata['tone_hint'] = verbalized.derived_action.tone_hint
            intent_snapshot_metadata['response_mode'] = verbalized.derived_action.response_mode
            intent_snapshot_metadata['answer_goal'] = verbalized.derived_action.answer_goal
            if isinstance(conclusion_view.metadata, dict):
                conclusion_view.metadata['previous_tone_hint'] = verbalized.derived_action.tone_hint
        thought_result.metadata['intent_snapshot'] = intent_snapshot_metadata

        assistant_claim_domain = self.ingest_service.trust_policy.infer_claim_domain(
            verbalized.user_response,
            source_type='assistant',
        )
        assistant_ingest = self.ingest_service.ingest(
            GraphIngestRequest(
                session_id=request.session_id,
                turn_index=request.turn_index,
                role='assistant',
                content=verbalized.user_response,
                metadata={
                    'source': 'assistant_reply',
                    'model_name': request.model_name,
                    'intent_snapshot': intent_snapshot_metadata,
                },
                source_type='assistant',
                claim_domain=assistant_claim_domain,
            )
        )

        activation_debug = {
            'seed_blocks': [
                {
                    'block_kind': block.block_kind,
                    'text': block.text,
                    'normalized_text': block.normalized_text,
                }
                for block in thought_view.seed_blocks
            ],
            'seed_node_ids': [item.node.id for item in thought_view.seed_nodes if item.node.id is not None],
            'local_node_ids': [node.id for node in thought_view.nodes if node.id is not None],
            'local_edge_ids': [edge.id for edge in thought_view.edges if edge.id is not None],
            'pointer_ids': [pointer.id for pointer in thought_view.pointers if pointer.id is not None],
            'metadata': thought_view.metadata,
        }

        thinking_debug = {
            'signal_count': len(thought_result.contradiction_signals),
            'trust_update_count': len(thought_result.trust_updates),
            'revision_action_count': len(thought_result.revision_actions),
            'signals': [asdict(item) for item in thought_result.contradiction_signals],
            'trust_updates': [asdict(item) for item in thought_result.trust_updates],
            'revision_actions': [asdict(item) for item in thought_result.revision_actions],
            'conclusion_view': {
                'intent_keywords': conclusion_view.intent_keywords,
                'inferred_intent': conclusion_view.inferred_intent,
                'aligned_node_count': len(conclusion_view.intent_aligned_nodes),
                'supporting_edge_count': len(conclusion_view.supporting_edges),
                'contradicted_node_count': len(conclusion_view.contradicted_nodes),
                'confidence': conclusion_view.confidence,
                'explanation_summary': conclusion_view.explanation_summary,
                'activated_concepts': conclusion_view.activated_concepts,
                'key_relations': conclusion_view.key_relations,
                'detected_conflicts': [asdict(c) for c in conclusion_view.detected_conflicts],
                'revision_decisions': [asdict(r) for r in conclusion_view.revision_decisions],
                'trust_changes': [asdict(t) for t in conclusion_view.trust_changes],
            },
            'derived_action': asdict(verbalized.derived_action),
            'metadata': thought_result.metadata,
        }

        search_grounding = self._build_search_grounding_state(search_run)
        search_debug = {
            'query_triggered': bool(search_run.attempted),
            'planning_attempted': bool(getattr(search_run, 'planning_attempted', False)),
            'need_decision': {
                'need_search': search_run.decision.need_search,
                'reason': search_run.decision.reason,
                'gap_summary': search_run.decision.gap_summary,
                'target_terms': search_run.decision.target_terms,
                'requested_slots': search_run.decision.requested_slots,
                'covered_slots': search_run.decision.covered_slots,
                'missing_slots': search_run.decision.missing_slots,
                'slot_supports': search_run.decision.slot_supports,
                'scope_gate_attempted': bool(search_run.decision.metadata.get('scope_gate_attempted')),
                'scope_gate': search_run.decision.metadata.get('scope_gate'),
                'scope_gate_error': search_run.decision.metadata.get('scope_gate_error'),
            },
            'slot_plan': {
                'entities': search_run.slot_plan.entities,
                'aspects': search_run.slot_plan.aspects,
                'comparison_axes': search_run.slot_plan.comparison_axes,
                'requested_slots': [slot.label for slot in search_run.slot_plan.requested_slots],
                'reason': search_run.slot_plan.reason,
            } if search_run.slot_plan else None,
            'plan': {
                'queries': search_run.plan.queries,
                'reason': search_run.plan.reason,
                'focus_terms': search_run.plan.focus_terms,
                'issued_slot_queries': (search_run.plan.metadata or {}).get('issued_slot_queries', []),
                'planned_aspect_extraction': (search_run.plan.metadata or {}).get('planned_aspect_extraction', []),
            } if search_run.plan else None,
            'results': [asdict(item) for item in all_search_results],
            'provider_errors': search_grounding['provider_errors'],
            'grounded_terms': search_grounding['grounded_terms'],
            'missing_terms': search_grounding['missing_terms'],
            'missing_aspects': search_grounding['missing_aspects'],
            'no_evidence_found': search_grounding['no_evidence_found'],
            'ingest': [
                {
                    'message_id': item.message_id,
                    'root_event_id': item.root_event_id,
                    'created_node_ids': item.created_node_ids,
                    'reused_node_ids': item.reused_node_ids,
                    'created_edge_ids': item.created_edge_ids,
                    'supported_edge_ids': item.supported_edge_ids,
                }
                for item in search_ingest_results
            ],
            'error': search_run.error,
        }

        assistant_ingest_debug = {
            'message_id': assistant_ingest.message_id,
            'root_event_id': assistant_ingest.root_event_id,
            'block_count': assistant_ingest.block_count,
            'created_node_ids': assistant_ingest.created_node_ids,
            'reused_node_ids': assistant_ingest.reused_node_ids,
            'created_edge_ids': assistant_ingest.created_edge_ids,
            'supported_edge_ids': assistant_ingest.supported_edge_ids,
        }

        debug_payload = {
            'model_edge_assertion': model_edge_assertion_result.to_debug(),
            'connect_type_promotion': connect_type_promotion_result.to_debug(),
            'temporary_edge_cleanup': temporary_edge_cleanup_result.to_debug(),
            'revision_policy': self._revision_policy_debug(),
            'ingest': {
                'message_id': ingest_result.message_id,
                'root_event_id': ingest_result.root_event_id,
                'block_count': ingest_result.block_count,
                'created_node_ids': ingest_result.created_node_ids,
                'reused_node_ids': ingest_result.reused_node_ids,
                'created_edge_ids': ingest_result.created_edge_ids,
                'supported_edge_ids': ingest_result.supported_edge_ids,
                'created_pointer_ids': ingest_result.created_pointer_ids,
                'source_type': ingest_result.source_type,
                'claim_domain': ingest_result.claim_domain,
            },
            'activation': activation_debug,
            'thinking': thinking_debug,
            'search': search_debug,
            'assistant_ingest': assistant_ingest_debug,
            'verbalization': {
                'used_llm': verbalized.used_llm,
                'llm_error': verbalized.llm_error,
                'llm_error_code': verbalized.llm_error_code,
                'preservation_action': verbalized.preservation_action,
                'preservation_reason': verbalized.preservation_reason,
                'preservation_violations': verbalized.preservation_violations or [],
            },
        }

        return {
            'reply': verbalized.user_response,
            'internal_explanation': verbalized.internal_explanation,
            'used_model': request.model_name,
            'project_id': None,
            'project_name': None,
            'debug': debug_payload,
            'ingest': debug_payload['ingest'],
            'activation': activation_debug,
            'thinking': thinking_debug,
            'search': search_debug,
            'assistant_ingest': assistant_ingest_debug,
            'verbalization': debug_payload['verbalization'],
        }

    def next_turn_index(self, session_id: str) -> int:
        with self._uow_factory() as uow:
            rows = [row for row in uow.chat_messages.list_by_session(session_id, limit=100000) if row.role == 'user']
            return (rows[-1].turn_index + 1) if rows else 1

    def run_internal_revision_review(
        self,
        *,
        limit: int = 100,
        trigger: str = 'system_internal',
    ) -> dict[str, Any]:
        actions = self.thought_engine.run_revision_review(
            message_id=None,
            limit=max(1, int(limit)),
            trigger=trigger,
        )
        return {
            'ok': True,
            'action_count': len(actions),
            'actions': [asdict(item) for item in actions],
            'trigger': trigger,
        }

    def _raise_if_search_requires_model_selection(
        self,
        *,
        request: ChatPipelineRequest,
        search_run: SearchRunResult,
    ) -> None:
        if not search_run.decision.need_search or not search_run.error:
            return
        if search_run.error != SEARCH_MODEL_SELECTION_REQUIRED_ERROR:
            return
        if request.model_name.strip() and request.model_name != DEFAULT_MODEL_NAME:
            return
        raise UserFacingChatError(
            '이 질문은 외부 검색이 필요한데 검색 계획용 모델이 선택되지 않았습니다. '
            '상단의 모델 선택에서 Ollama 모델을 고른 뒤 다시 시도해주세요.'
        )

    def _attach_search_context(self, conclusion: 'ConclusionView', *, search_run: SearchRunResult) -> None:
        if conclusion is None:
            return
        if conclusion.metadata is None:
            conclusion.metadata = {}
        search_grounding = self._build_search_grounding_state(search_run)
        conclusion.metadata['search_context'] = {
            'need_search': bool(search_run.decision.need_search),
            'attempted': bool(search_run.attempted),
            'result_count': len(search_run.results),
            'reason': search_run.decision.reason,
            'target_terms': search_run.decision.target_terms,
            'requested_slots': search_run.decision.requested_slots,
            'covered_slots': search_run.decision.covered_slots,
            'missing_slots': search_run.decision.missing_slots,
            'slot_supports': search_run.decision.slot_supports,
            'grounded_terms': search_grounding['grounded_terms'],
            'missing_terms': search_grounding['missing_terms'],
            'missing_aspects': search_grounding['missing_aspects'],
            'slot_entities': search_run.slot_plan.entities if search_run.slot_plan else [],
            'slot_aspects': search_run.slot_plan.aspects if search_run.slot_plan else [],
            'comparison_axes': search_run.slot_plan.comparison_axes if search_run.slot_plan else [],
            'planned_queries': search_run.plan.queries if search_run.plan else [],
            'issued_slot_queries': (search_run.plan.metadata or {}).get('issued_slot_queries', []) if search_run.plan else [],
            'error': search_run.error,
            'provider_errors': search_grounding['provider_errors'],
            'no_evidence_found': search_grounding['no_evidence_found'],
            'scope_gate_attempted': bool(search_run.decision.metadata.get('scope_gate_attempted')),
            'scope_gate': search_run.decision.metadata.get('scope_gate'),
            'scope_gate_error': search_run.decision.metadata.get('scope_gate_error'),
            'summaries': [
                {
                    'title': item.title,
                    'snippet': item.snippet,
                    'passages': list(item.passages[:2]),
                    'provider': item.provider,
                    'url': item.url,
                }
                for item in search_run.results[:3]
            ],
        }

    def _build_search_grounding_state(self, search_run: SearchRunResult) -> dict[str, Any]:
        grounded_terms = self._unique_slot_values(search_run.decision.covered_slots, key='entity')
        missing_terms = self._unique_slot_values(search_run.decision.missing_slots, key='entity')
        missing_aspects = self._unique_slot_values(search_run.decision.missing_slots, key='aspect')
        provider_errors = list(getattr(search_run, 'provider_errors', []) or [])
        no_evidence_found = bool(
            search_run.decision.need_search
            and search_run.attempted
            and not search_run.results
            and not search_run.error
            and not provider_errors
        )
        return {
            'grounded_terms': grounded_terms,
            'missing_terms': missing_terms,
            'missing_aspects': missing_aspects,
            'provider_errors': provider_errors,
            'no_evidence_found': no_evidence_found,
        }

    def _unique_slot_values(self, slots: list[dict[str, Any]], *, key: str) -> list[str]:
        values: list[str] = []
        for slot in slots or []:
            token = ' '.join(str(slot.get(key) or '').split()).strip()
            if not token or token in values:
                continue
            values.append(token)
        return values

    def _load_revision_rule_overrides(
        self,
        path_token: str | Path | None,
        *,
        strict: bool,
    ) -> tuple[dict[str, dict[str, object]], str, str]:
        raw_path = str(path_token or '').strip()
        if not raw_path:
            return {}, '', ''
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (PROJECT_ROOT / candidate).resolve()
        display_path = str(candidate)
        try:
            if not candidate.exists():
                return {}, display_path, ''
            payload = json.loads(candidate.read_text(encoding='utf-8'))
            normalized = self._normalize_rule_overrides(payload)
            if not normalized:
                raise ValueError('override file exists but no valid rule override entries were found')
            return normalized, display_path, ''
        except Exception as exc:  # pragma: no cover - defensive path
            if strict:
                raise RuntimeError(f'failed to load revision rule overrides: {exc}') from exc
            return {}, display_path, str(exc)

    def _normalize_rule_overrides(self, payload: object) -> dict[str, dict[str, object]]:
        if not isinstance(payload, dict):
            return {}
        result: dict[str, dict[str, object]] = {}
        for rule_name, override in payload.items():
            name = ' '.join(str(rule_name or '').split()).strip()
            if not name or not isinstance(override, dict):
                continue
            normalized: dict[str, object] = {}
            for key, value in override.items():
                token = ' '.join(str(key or '').split()).strip()
                if not token:
                    continue
                normalized[token] = value
            if normalized:
                result[name] = normalized
        return result

    def _revision_policy_debug(self) -> dict[str, Any]:
        return {
            'profile': self.revision_rule_profile,
            'override_path': self.revision_rule_override_path,
            'override_load_error': self.revision_rule_override_load_error or None,
            'override_rule_count': len(self.revision_rule_overrides),
            'overrides_loaded': bool(self.revision_rule_overrides),
        }
