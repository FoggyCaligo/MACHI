import unittest

from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.entities.conclusion import CoreConclusion
from core.entities.intent import IntentSnapshot
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.search.search_sidecar import SearchSidecar
from core.thinking.conclusion_builder import ConclusionBuilder, MissingIntentSnapshotError
from core.update.source_trust_policy import SourceTrustPolicy
from core.verbalization.action_layer_builder import ActionLayerBuilder


class TestNoStringHeuristics(unittest.TestCase):
    def test_source_trust_domain_depends_on_source_only(self):
        policy = SourceTrustPolicy()
        self.assertEqual(policy.infer_claim_domain('나는 빨간색을 좋아해', source_type='user'), 'general_claim')
        self.assertEqual(policy.infer_claim_domain('나에 대해 기억해?', source_type='user'), 'general_claim')
        self.assertEqual(policy.infer_claim_domain('무엇의 의미를 설명해줘', source_type='search'), 'world_fact')

    def test_conclusion_builder_requires_explicit_intent_snapshot(self):
        builder = ConclusionBuilder()
        thought_view = ThoughtView(session_id='s1', message_text='수정 구현 진행')
        with self.assertRaises(MissingIntentSnapshotError):
            builder.build(
                request=type('Req', (), {'session_id': 's1', 'message_id': 1, 'message_text': '수정 구현 진행'})(),
                thought_view=thought_view,
                contradiction_signals=[],
                trust_updates=[],
                revision_actions=[],
                intent_snapshot=None,
            )

    def test_action_layer_ignores_keyword_text(self):
        builder = ActionLayerBuilder()
        conclusion = CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='기억 설명 수정 구현 안녕',
            inferred_intent='graph_grounded_reasoning',
            activated_concepts=[1],
            key_relations=[],
        )
        action = builder.build(conclusion)
        self.assertEqual(action.response_mode, 'direct_answer_with_uncertainty')

    def test_search_sidecar_uses_graph_state_not_message_keywords(self):
        sidecar = SearchSidecar()
        seed_node = Node(id=1, raw_value='테스트', normalized_value='테스트', node_kind='noun_phrase')
        thought_view = ThoughtView(
            session_id='s1',
            message_text='이건 뭐야',
            seed_nodes=[ActivatedNode(node=seed_node, activation_score=1.0, activated_by='seed')],
            nodes=[seed_node],
            edges=[],
            pointers=[],
            activated_patterns=[],
        )
        conclusion = CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='test',
            inferred_intent='open_information_request',
            activated_concepts=[1],
            key_relations=[],
        )
        self.assertFalse(sidecar.should_search('이건 뭐야', thought_view, conclusion))

    def test_input_segmenter_has_no_keyword_sentence_kind(self):
        segmenter = InputSegmenter(hash_resolver=HashResolver())
        blocks = segmenter.segment('수정 구현 진행')
        self.assertEqual(blocks[0].block_kind, 'statement_phrase')

    def test_input_segmenter_keeps_tokens_without_stopword_fallback(self):
        segmenter = InputSegmenter(hash_resolver=HashResolver())
        blocks = segmenter.segment('그리고 지금 기준')
        normalized = [block.normalized_text for block in blocks if block.block_kind == 'noun_phrase']
        self.assertIn('그리고', normalized)
        self.assertIn('지금', normalized)
        self.assertIn('기준', normalized)


if __name__ == '__main__':
    unittest.main()
