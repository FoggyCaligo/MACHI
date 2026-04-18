from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.cognition.meaning_block import MeaningBlock
from core.entities.chat_message import ChatMessage
from core.search.search_sidecar import SearchEvidence, SearchRunResult, SearchSidecar
from core.thinking.structure_revision_service import StructureRevisionService
from core.thinking.thought_engine import ThoughtEngine, ThoughtRequest
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestResult, GraphIngestService
from core.update.node_merge_service import NodeMergeService
from core.verbalization.verbalizer import Verbalizer
from storage.sqlite.unit_of_work import SqliteUnitOfWork

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / 'data' / 'memory.db'
SCHEMA_PATH = PROJECT_ROOT / 'storage' / 'schema.sql'
DEFAULT_MODEL_NAME = 'mk5-graph-core'


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
        model_feedback_service: object | None = None,
        model_edge_assertion_service: object | None = None,
        connect_type_promotion_service: object | None = None,
        graph_commit_service: object | None = None,
        temporary_edge_service: object | None = None,
        revision_rule_overrides_path: str | Path | None = None,
        revision_rule_profile: str = '',
        revision_rule_overrides_strict: bool = False,
    ) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        self.revision_rule_overrides = {}
        self.revision_rule_override_path = str(revision_rule_overrides_path or '')
        self.revision_rule_override_load_error = ''
        self.revision_rule_profile = revision_rule_profile or ''
        self.slimmed_runtime = True
        self.disabled_runtime_layers = [
            'pattern_detector',
            'temporary_edge_service',
            'model_feedback_service',
            'model_edge_assertion_service',
            'connect_type_promotion_service',
            'revision_rule_analytics',
            'revision_rule_tuner',
            'revision_rule_scheduler',
            'revision_rule_override_automation',
        ]
        self.ingest_service = GraphIngestService(self._uow_factory)
        self.activation_engine = ActivationEngine(self._uow_factory)
        self.thought_engine = ThoughtEngine(
            self._uow_factory,
            structure_revision_service=StructureRevisionService(
                node_merge_service=NodeMergeService(self._uow_factory),
                rule_overrides={},
            ),
        )
        self.verbalizer = verbalizer or Verbalizer()
        self.search_sidecar = search_sidecar or SearchSidecar()
        self.model_feedback_service = None
        self.model_edge_assertion_service = None
        self.connect_type_promotion_service = None
        self.graph_commit_service = None
        self.temporary_edge_service = None

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

        analyzed_blocks, meaning_analysis = self._analyze_meaning_blocks(
            message=request.message,
            seed_blocks=ingest_result.blocks,
            model_name=request.model_name,
        )
        resolved_nodes = self._resolve_blocks_directly(analyzed_blocks)

        search_run = self.search_sidecar.run(
            message=request.message,
            meaning_blocks=analyzed_blocks,
            resolved_nodes=resolved_nodes,
            current_root_event_id=ingest_result.root_event_id,
            model_name=request.model_name,
        )
        self._raise_if_search_requires_model_selection(request=request, search_run=search_run)

        search_results: list[SearchEvidence] = search_run.results
        search_ingest_results: list[GraphIngestResult] = []
        if search_results:
            for index, item in enumerate(search_results, start=1):
                compact_blocks = self._build_search_evidence_blocks(item)
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
                                'evidence_passages': list(item.passages or []),
                                'compact_ingest': True,
                            },
                            source_type='search',
                            claim_domain=item.claim_domain,
                            persist_message=False,
                            blocks_override=compact_blocks,
                        )
                    )
                )

        thought_view = self.activation_engine.build_view(
            ActivationRequest(
                session_id=request.session_id,
                content=request.message,
                seed_blocks=analyzed_blocks,
                current_root_event_id=ingest_result.root_event_id,
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

        thought_result.metadata['meaning_analysis'] = meaning_analysis
        thought_result.metadata['input_block_count'] = len(analyzed_blocks)
        thought_result.metadata['search_completed_before_think'] = True
        thought_result.metadata['search_result_count'] = len(search_results)
        thought_result.metadata['assistant_full_answer_ingest_removed'] = True
        thought_result.core_conclusion.metadata['meaning_analysis'] = meaning_analysis
        thought_result.core_conclusion.metadata['search_completed_before_think'] = True

        resolved_nodes = self._resolve_blocks_directly(analyzed_blocks)
        search_run.decision = self.search_sidecar.need_evaluator.evaluate(
            message=request.message,
            meaning_blocks=analyzed_blocks,
            resolved_nodes=resolved_nodes,
            current_root_event_id=ingest_result.root_event_id,
        )

        temporary_edge_cleanup_result = {'enabled': False, 'reason': 'slimmed_runtime_disabled'}
        model_feedback_result = {'enabled': False, 'reason': 'slimmed_runtime_disabled'}
        model_edge_assertion_result = {'enabled': False, 'reason': 'slimmed_runtime_disabled'}
        connect_type_promotion_result = {'enabled': False, 'reason': 'slimmed_runtime_disabled'}

        self._attach_search_context(thought_result.core_conclusion, search_run=search_run)

        verbalized = self.verbalizer.verbalize(thought_result.core_conclusion, model_name=request.model_name)
        if verbalized.llm_error or not verbalized.user_response:
            if verbalized.llm_error and verbalized.llm_error.startswith('template_verbalizer_disabled:'):
                raise RuntimeError('현재 응답을 생성할 수 있는 모델이 없습니다. 모델을 선택하거나 OLLAMA 환경을 확인해주세요.')
            if verbalized.llm_error_code == 'timeout':
                raise UserFacingChatError('선택한 모델의 응답 생성이 제한 시간 안에 끝나지 않았습니다. 더 빠른 모델로 바꾸거나, Ollama 상태와 모델 로드 상태를 확인한 뒤 다시 시도해주세요.')
            raise RuntimeError(f"Verbalization failed: {verbalized.llm_error or 'empty response from verbalizer'}")

        thought_result.derived_action = verbalized.derived_action
        intent_snapshot_metadata = dict(thought_result.metadata.get('intent_snapshot', {}) or {})
        if verbalized.derived_action is not None:
            intent_snapshot_metadata['tone_hint'] = verbalized.derived_action.tone_hint
            intent_snapshot_metadata['response_mode'] = verbalized.derived_action.response_mode
            intent_snapshot_metadata['answer_goal'] = verbalized.derived_action.answer_goal
            if thought_result.core_conclusion is not None and isinstance(thought_result.core_conclusion.metadata, dict):
                thought_result.core_conclusion.metadata['previous_tone_hint'] = verbalized.derived_action.tone_hint
        thought_result.metadata['intent_snapshot'] = intent_snapshot_metadata
        self._store_assistant_snapshot(request=request, response_text=verbalized.user_response, intent_snapshot=intent_snapshot_metadata, model_name=request.model_name)

        activation_debug = {
            'seed_blocks': [
                {
                    'block_kind': block.block_kind,
                    'text': block.text,
                    'normalized_text': block.normalized_text,
                    'metadata': block.metadata,
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
                'slot_supports': search_run.decision.slot_supports,
            },
            'slot_plan': None,
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
            'meaning_analysis': meaning_analysis,
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
            'enabled': False,
            'reason': 'assistant_full_answer_ingest_removed',
            'snapshot_saved': True,
        }

        debug_payload = {
            'model_feedback': model_feedback_result,
            'model_edge_assertion': model_edge_assertion_result,
            'connect_type_promotion': connect_type_promotion_result,
            'temporary_edge_cleanup': temporary_edge_cleanup_result,
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


    def _build_search_evidence_blocks(self, item: SearchEvidence) -> list[MeaningBlock]:
        title = ' '.join(str(item.title or '').split()).strip()
        title_norm = self.ingest_service.hash_resolver.normalize_text(title) if title else ''
        passage = ' '.join(str((item.passages or [''])[0] or item.snippet or '').split()).strip()
        if len(passage) > 220:
            passage = passage[:217].rstrip() + '...'
        statement_text = f'{title}: {passage}' if title and passage and passage != title else (passage or title)
        statement_norm = self.ingest_service.hash_resolver.normalize_text(statement_text)
        blocks: list[MeaningBlock] = []
        if statement_norm:
            blocks.append(MeaningBlock(
                text=statement_text,
                normalized_text=statement_norm,
                block_kind='statement_phrase',
                sentence_index=0,
                block_index=0,
                source_sentence=statement_text,
                metadata={'source': 'search_compact', 'address_scope': 'search_evidence_statement'},
            ))
        if title_norm:
            blocks.append(MeaningBlock(
                text=title,
                normalized_text=title_norm,
                block_kind='noun_phrase',
                sentence_index=0,
                block_index=1,
                source_sentence=statement_text or title,
                metadata={'source': 'search_compact', 'address_scope': 'search_evidence_title'},
            ))
        return blocks

    def _resolve_blocks_directly(self, blocks: list[MeaningBlock]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        with self._uow_factory() as uow:
            for block in blocks:
                if block.block_kind != 'noun_phrase':
                    continue
                term = ' '.join(str(block.normalized_text or block.text).split()).strip().lower()
                if not term or term in resolved:
                    continue
                lookup = self.ingest_service.accessor.resolve(uow.nodes, block)
                resolved[term] = lookup.node
        return resolved

    def _analyze_meaning_blocks(self, *, message: str, seed_blocks: list[MeaningBlock], model_name: str) -> tuple[list[MeaningBlock], dict[str, Any]]:
        annotated = [MeaningBlock(
            text=block.text,
            normalized_text=block.normalized_text,
            block_kind=block.block_kind,
            sentence_index=block.sentence_index,
            block_index=block.block_index,
            source_sentence=block.source_sentence,
            metadata=dict(block.metadata),
        ) for block in seed_blocks]
        analysis_result = self._similarity_meaning_analysis(message=message, blocks=annotated)
        self._apply_meaning_analysis(annotated, analysis_result)
        return annotated, analysis_result

    def _fallback_meaning_analysis(self, blocks: list[MeaningBlock]) -> dict[str, Any]:
        noun_blocks = [block for block in blocks if block.block_kind == 'noun_phrase']
        last_sentence = max((block.sentence_index for block in noun_blocks), default=0)
        primary: list[str] = []
        secondary: list[str] = []
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for block in noun_blocks:
            term = ' '.join(str(block.normalized_text or block.text).split()).strip().lower()
            if not term or term in seen:
                continue
            seen.add(term)
            importance = 'primary' if block.sentence_index == last_sentence else 'secondary'
            if importance == 'primary':
                primary.append(term)
            else:
                secondary.append(term)
            items.append(
                {
                    'normalized': term,
                    'importance': importance,
                    'search_policy': 'search_if_unusable',
                    'freshness_kind': 'unknown',
                }
            )
        return {
            'mode': 'fallback',
            'current_intent': 'graph_grounded_reasoning',
            'primary_keywords': primary[:6],
            'secondary_keywords': secondary[:6],
            'ignore_for_search': [],
            'items': items,
        }

    def _similarity_meaning_analysis(self, *, message: str, blocks: list[MeaningBlock]) -> dict[str, Any]:
        fallback = self._fallback_meaning_analysis(blocks)
        noun_blocks = [block for block in blocks if block.block_kind == 'noun_phrase']
        if not noun_blocks:
            return fallback

        statement_blocks = [block for block in blocks if block.block_kind == 'statement_phrase']
        question_statement = next(
            (block for block in reversed(statement_blocks) if '?' in str(block.text) or '？' in str(block.text)),
            statement_blocks[-1] if statement_blocks else None,
        )
        focus_text = str(question_statement.text if question_statement else message)
        focus_sentence_index = int(question_statement.sentence_index if question_statement else max((block.sentence_index for block in noun_blocks), default=0))
        focus_token_count = max(1, len(self._token_counter(focus_text)))
        prototypes = {
            'timeless': '무엇인지 설명 개요 정의 작품 인물 사물 일반 정보 역사 특징 기본 설명',
            'current_state': '현재 상태 최근 변화 지금 적용 여부 최신 업데이트 버전 동작 상황',
            'self_or_local': '지금 너 현재 대화 시스템 내부 로컬 그래프 세션 적용 느껴지는 상태',
        }

        scored_items: list[tuple[float, dict[str, str]]] = []
        for index, block in enumerate(noun_blocks):
            term = ' '.join(str(block.normalized_text or block.text).split()).strip().lower()
            if not term:
                continue
            sentence_text = str(block.source_sentence or block.text)
            sentence_focus = self._cosine_similarity(sentence_text, focus_text)
            term_focus = self._cosine_similarity(term, focus_text)
            message_focus = self._cosine_similarity(term, message)
            position_boost = 0.25 if block.sentence_index == focus_sentence_index else 0.0
            short_penalty = 0.08 if len(term) <= 1 else 0.0
            focus_score = (0.50 * sentence_focus) + (0.35 * term_focus) + (0.15 * message_focus) + position_boost - short_penalty

            freshness_scores = {
                name: self._cosine_similarity(f'{focus_text} {sentence_text} {term}', proto)
                for name, proto in prototypes.items()
            }
            freshness_kind = max(freshness_scores, key=freshness_scores.get)
            freshness_score = freshness_scores[freshness_kind]
            if freshness_score < 0.08:
                freshness_kind = 'unknown'

            importance = 'secondary'
            if focus_score >= 0.48:
                importance = 'primary'
            elif focus_score >= 0.24:
                importance = 'secondary'
            elif block.sentence_index == focus_sentence_index and len(term) >= 2:
                importance = 'secondary'
            elif focus_score < 0.10 and len(term) <= 2:
                importance = 'ignore'
            else:
                importance = 'background'

            search_policy = 'search_if_unusable'
            if importance == 'ignore':
                search_policy = 'ignore'
            elif freshness_kind == 'self_or_local':
                search_policy = 'local_only'

            item = {
                'normalized': term,
                'importance': importance,
                'search_policy': search_policy,
                'freshness_kind': freshness_kind,
            }
            score_with_tiebreak = focus_score + ((focus_token_count - index) / (focus_token_count * 1000.0))
            scored_items.append((score_with_tiebreak, item))

        if not scored_items:
            return fallback

        best_item = max(scored_items, key=lambda item: item[0])[1]
        current_intent = 'graph_grounded_reasoning'
        if best_item['freshness_kind'] == 'self_or_local':
            current_intent = 'local_state_check'
        elif best_item['freshness_kind'] == 'current_state':
            current_intent = 'state_grounding_request'

        items = [item for _, item in scored_items]
        primary = [item['normalized'] for _, item in scored_items if item['importance'] == 'primary']
        secondary = [item['normalized'] for _, item in scored_items if item['importance'] == 'secondary']
        ignore_for_search = [item['normalized'] for _, item in scored_items if item['search_policy'] == 'ignore']

        if not primary and secondary:
            primary = secondary[:1]
            for item in items:
                if item['normalized'] == primary[0] and item['importance'] == 'secondary':
                    item['importance'] = 'primary'
                    break
            secondary = [item['normalized'] for item in items if item['importance'] == 'secondary']

        return {
            'mode': 'similarity',
            'current_intent': current_intent,
            'primary_keywords': primary[:6],
            'secondary_keywords': secondary[:8],
            'ignore_for_search': ignore_for_search[:8],
            'items': items,
        }

    def _token_counter(self, text: str) -> Counter[str]:
        tokens = [token.lower() for token in re.findall(r'[0-9A-Za-z가-힣_+-]+', str(text or '')) if token.strip()]
        return Counter(tokens)

    def _cosine_similarity(self, left: str, right: str) -> float:
        left_counter = self._token_counter(left)
        right_counter = self._token_counter(right)
        if not left_counter or not right_counter:
            return 0.0
        dot = sum(left_counter[token] * right_counter.get(token, 0) for token in left_counter)
        if dot <= 0:
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left_counter.values()))
        right_norm = math.sqrt(sum(value * value for value in right_counter.values()))
        if left_norm <= 0.0 or right_norm <= 0.0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _apply_meaning_analysis(self, blocks: list[MeaningBlock], analysis: dict[str, Any]) -> None:
        item_map: dict[str, dict[str, str]] = {}
        for item in analysis.get('items') or []:
            if not isinstance(item, dict):
                continue
            term = ' '.join(str(item.get('normalized') or '').split()).strip().lower()
            if not term:
                continue
            item_map[term] = {
                'importance': str(item.get('importance') or 'secondary').strip(),
                'search_policy': str(item.get('search_policy') or 'search_if_unusable').strip(),
                'freshness_kind': str(item.get('freshness_kind') or 'unknown').strip(),
            }
        for block in blocks:
            if block.block_kind != 'noun_phrase':
                continue
            term = ' '.join(str(block.normalized_text or block.text).split()).strip().lower()
            item = item_map.get(term) or {'importance': 'secondary', 'search_policy': 'search_if_unusable', 'freshness_kind': 'unknown'}
            block.metadata['importance'] = item['importance']
            block.metadata['search_policy'] = item['search_policy']
            block.metadata['freshness_kind'] = item['freshness_kind']
            block.metadata['analysis_source'] = analysis.get('mode') or 'fallback'
        for block in blocks:
            block.metadata.setdefault('analysis_intent', str(analysis.get('current_intent') or 'graph_grounded_reasoning'))

    def _store_assistant_snapshot(self, *, request: ChatPipelineRequest, response_text: str, intent_snapshot: dict[str, Any], model_name: str) -> None:
        metadata = {
            'source': 'assistant_snapshot',
            'source_type': 'assistant_snapshot',
            'model_name': model_name,
            'intent_snapshot': intent_snapshot,
        }
        with self._uow_factory() as uow:
            uow.chat_messages.add(
                ChatMessage(
                    message_uid=f'msg_{uuid4().hex}',
                    session_id=request.session_id,
                    turn_index=request.turn_index,
                    role='assistant',
                    content=response_text,
                    content_hash=self.ingest_service.hash_resolver.content_hash(response_text),
                    attached_files=[],
                    metadata=metadata,
                )
            )
            uow.commit()

    def run_internal_revision_review(self, *, limit: int = 100, trigger: str = 'system_internal') -> dict[str, Any]:
        actions = self.thought_engine.run_revision_review(message_id=None, limit=max(1, int(limit)), trigger=trigger)
        return {'ok': True, 'action_count': len(actions), 'actions': [asdict(item) for item in actions], 'trigger': trigger}

    def _raise_if_search_requires_model_selection(self, *, request: ChatPipelineRequest, search_run: SearchRunResult) -> None:
        error = ' '.join(str(search_run.error or '').split()).lower()
        if not error:
            return
        if 'model' in error and ('require' in error or 'selection' in error or 'selectable' in error):
            raise UserFacingChatError('검색이 필요하지만 현재 선택된 모델로는 구조 해석/검색 계획을 진행할 수 없습니다. 모델을 선택한 뒤 다시 시도해주세요.')

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
            'slot_supports': search_run.decision.slot_supports,
            'grounded_terms': search_grounding['grounded_terms'],
            'missing_terms': search_grounding['missing_terms'],
            'missing_aspects': search_grounding['missing_aspects'],
            'planned_queries': search_run.plan.queries if search_run.plan else [],
            'issued_slot_queries': (search_run.plan.metadata or {}).get('issued_slot_queries', []) if search_run.plan else [],
            'error': search_run.error,
            'provider_errors': search_grounding['provider_errors'],
            'no_evidence_found': search_grounding['no_evidence_found'],
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
        provider_errors = list(getattr(search_run, 'provider_errors', []) or [])
        no_evidence_found = bool(search_run.decision.need_search and search_run.attempted and not search_run.results and not search_run.error and not provider_errors)
        return {
            'grounded_terms': grounded_terms,
            'missing_terms': missing_terms,
            'missing_aspects': [],
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

    def _load_revision_rule_overrides(self, path_token: str | Path | None, *, strict: bool) -> tuple[dict[str, dict[str, object]], str, str]:
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
        except Exception as exc:  # pragma: no cover
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
