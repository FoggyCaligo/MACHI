from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.search.search_sidecar import SearchEvidence, SearchRunResult, SearchSidecar
from core.thinking.thought_engine import ThoughtEngine, ThoughtRequest
from core.update.graph_commit_service import GraphCommitService
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestResult, GraphIngestService
from core.update.model_edge_assertion_service import ModelEdgeAssertionResult, ModelEdgeAssertionService
from core.update.model_feedback_service import ModelFeedbackResult, ModelFeedbackService
from core.verbalization.verbalizer import Verbalizer
from storage.sqlite.unit_of_work import SqliteUnitOfWork


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / 'data' / 'memory.db'
SCHEMA_PATH = PROJECT_ROOT / 'storage' / 'schema.sql'
DEFAULT_MODEL_NAME = 'mk5-graph-core'
SEARCH_MODEL_SELECTION_REQUIRED_ERROR = 'question slot planner requires a selectable LLM model'


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
        model_feedback_service: ModelFeedbackService | None = None,
        model_edge_assertion_service: ModelEdgeAssertionService | None = None,
        graph_commit_service: GraphCommitService | None = None,
    ) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        self.ingest_service = GraphIngestService(self._uow_factory)
        self.activation_engine = ActivationEngine(self._uow_factory)
        self.thought_engine = ThoughtEngine(self._uow_factory)
        self.verbalizer = verbalizer or Verbalizer()
        self.search_sidecar = search_sidecar or SearchSidecar()
        self.model_feedback_service = model_feedback_service or ModelFeedbackService()
        self.model_edge_assertion_service = model_edge_assertion_service or ModelEdgeAssertionService(self._uow_factory)
        self.graph_commit_service = graph_commit_service or GraphCommitService(self._uow_factory)

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
        search_results: list[SearchEvidence] = search_run.results
        search_ingest_results: list[GraphIngestResult] = []
        if search_results:
            for index, item in enumerate(search_results, start=1):
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
                raise RuntimeError('ThoughtEngine did not produce core_conclusion after search enrichment')
            if search_run.slot_plan is not None and not search_run.decision.metadata.get('post_search_refined'):
                search_run.decision = self.search_sidecar.need_evaluator.evaluate(
                    message=request.message,
                    thought_view=thought_view,
                    conclusion=thought_result.core_conclusion,
                    slot_plan=search_run.slot_plan,
                )

        # ── Model feedback: LLM이 본 그래프 상태를 기반으로 엣지 trust를 조정 ──────
        # Ollama 모델이 선택된 경우에만 실행. mk5-graph-core는 no-op.
        model_feedback_result = self.model_feedback_service.extract(
            model_name=request.model_name,
            message=request.message,
            thought_view=thought_view,
            conclusion=thought_result.core_conclusion,
        )
        if model_feedback_result.plan is not None:
            self.graph_commit_service.commit(model_feedback_result.plan)

        model_edge_assertion_result: ModelEdgeAssertionResult = self.model_edge_assertion_service.assert_edges(
            model_name=request.model_name,
            message=request.message,
            thought_view=thought_view,
        )

        self._attach_search_context(thought_result.core_conclusion, search_run=search_run)

        verbalized = self.verbalizer.verbalize(thought_result.core_conclusion, model_name=request.model_name)
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
            if thought_result.core_conclusion is not None and isinstance(thought_result.core_conclusion.metadata, dict):
                thought_result.core_conclusion.metadata['previous_tone_hint'] = verbalized.derived_action.tone_hint
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
            'core_conclusion': asdict(thought_result.core_conclusion),
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
            'results': [asdict(item) for item in search_results],
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
            'model_feedback': model_feedback_result.to_debug(),
            'model_edge_assertion': model_edge_assertion_result.to_debug(),
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

    def _attach_search_context(self, conclusion, *, search_run: SearchRunResult) -> None:
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
            'summaries': [
                {
                    'title': item.title,
                    'snippet': item.snippet,
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
