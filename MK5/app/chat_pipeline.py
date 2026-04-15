from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.search.search_sidecar import SearchEvidence, SearchRunResult, SearchSidecar
from core.thinking.thought_engine import ThoughtEngine, ThoughtRequest
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestResult, GraphIngestService
from core.verbalization.verbalizer import Verbalizer
from storage.sqlite.unit_of_work import SqliteUnitOfWork


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / 'data' / 'memory.db'
SCHEMA_PATH = PROJECT_ROOT / 'storage' / 'schema.sql'
DEFAULT_MODEL_NAME = 'mk5-graph-core'


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
    ) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        self.ingest_service = GraphIngestService(self._uow_factory)
        self.activation_engine = ActivationEngine(self._uow_factory)
        self.thought_engine = ThoughtEngine(self._uow_factory)
        self.verbalizer = verbalizer or Verbalizer()
        self.search_sidecar = search_sidecar or SearchSidecar()

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
        search_results: list[SearchEvidence] = list(search_run.results)
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
                                'source_provenance': item.source_provenance,
                                'trust_hint': item.trust_hint,
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

        grounded_terms, missing_terms = self._compute_search_coverage(search_run)
        self._attach_search_context(
            thought_result.core_conclusion,
            search_run=search_run,
            grounded_terms=grounded_terms,
            missing_terms=missing_terms,
        )

        verbalized = self.verbalizer.verbalize(thought_result.core_conclusion, model_name=request.model_name)
        if verbalized.llm_error or not verbalized.user_response:
            if verbalized.llm_error and verbalized.llm_error.startswith('template_verbalizer_disabled:'):
                raise RuntimeError(
                    '현재 응답을 생성할 수 있는 모델이 없습니다. 모델을 선택하거나 OLLAMA 환경을 확인해주세요.'
                )
            raise RuntimeError(
                f"Verbalization failed: {verbalized.llm_error or 'empty response from verbalizer'}"
            )

        thought_result.derived_action = verbalized.derived_action

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
                    'intent_snapshot': thought_result.metadata.get('intent_snapshot', {}),
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

        search_debug = {
            'query_triggered': bool(search_run.attempted),
            'need_decision': asdict(search_run.decision),
            'plan': asdict(search_run.plan) if search_run.plan is not None else None,
            'results': [asdict(item) for item in search_results],
            'provider_errors': [asdict(item) for item in search_run.provider_errors],
            'grounded_terms': grounded_terms,
            'missing_terms': missing_terms,
            'error': search_run.error,
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
            },
            'derived_action': asdict(verbalized.derived_action),
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
            'derived_action': debug_payload['derived_action'],
        }

    def next_turn_index(self, session_id: str) -> int:
        with self._uow_factory() as uow:
            rows = [row for row in uow.chat_messages.list_by_session(session_id, limit=100000) if row.role == 'user']
            return (rows[-1].turn_index + 1) if rows else 1

    def _attach_search_context(
        self,
        conclusion,
        *,
        search_run: SearchRunResult,
        grounded_terms: list[str],
        missing_terms: list[str],
    ) -> None:
        if conclusion is None:
            return
        if conclusion.metadata is None:
            conclusion.metadata = {}
        conclusion.metadata['search_context'] = {
            'attempted': bool(search_run.attempted),
            'result_count': len(search_run.results),
            'error': search_run.error,
            'provider_errors': [asdict(item) for item in search_run.provider_errors],
            'focus_terms': list(search_run.plan.focus_terms) if search_run.plan is not None else [],
            'grounded_terms': grounded_terms,
            'missing_terms': missing_terms,
            'summaries': [
                {
                    'title': item.title,
                    'snippet': item.snippet,
                    'provider': item.provider,
                    'url': item.url,
                    'trust_hint': item.trust_hint,
                    'source_provenance': item.source_provenance,
                }
                for item in search_run.results[:3]
            ],
        }

    def _compute_search_coverage(self, search_run: SearchRunResult) -> tuple[list[str], list[str]]:
        if search_run.plan is None:
            return [], []
        focus_terms = [term for term in search_run.plan.focus_terms if term]
        if not focus_terms:
            return [], []
        grounded_keys = {
            self._normalize_term(item.title)
            for item in search_run.results
            if item.title
        }
        grounded_terms: list[str] = []
        missing_terms: list[str] = []
        seen: set[str] = set()
        for term in focus_terms:
            key = self._normalize_term(term)
            if not key or key in seen:
                continue
            seen.add(key)
            if key in grounded_keys:
                grounded_terms.append(term)
            else:
                missing_terms.append(term)
        return grounded_terms, missing_terms

    def _normalize_term(self, text: str) -> str:
        compact = re.sub(r'[^0-9a-zA-Z가-힣]+', '', str(text or '').lower())
        return compact
