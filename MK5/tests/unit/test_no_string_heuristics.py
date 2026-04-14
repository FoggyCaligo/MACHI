import unittest

from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.search.search_sidecar import SearchSidecar
from core.thinking.conclusion_builder import ConclusionBuilder
from core.update.source_trust_policy import SourceTrustPolicy
from core.verbalization.action_layer_builder import ActionLayerBuilder


class TestNoStringHeuristics(unittest.TestCase):
    def test_source_trust_domain_depends_on_source_only(self):
        policy = SourceTrustPolicy()
        self.assertEqual(policy.infer_claim_domain('나는 빨간색을 좋아해', source_type='user'), 'general_claim')
        self.assertEqual(policy.infer_claim_domain('나에 대해 기억해?', source_type='user'), 'general_claim')
        self.assertEqual(policy.infer_claim_domain('무엇의 의미를 설명해줘', source_type='search'), 'world_fact')

    def test_conclusion_intent_depends_on_graph_state(self):
        builder = ConclusionBuilder()
        thought_view = ThoughtView(
            session_id='s1',
            message_text='수정 구현 진행',
            seed_nodes=[],
            nodes=[],
            edges=[],
            pointers=[],
            activated_patterns=[],
        )
        conclusion = builder.build(
            request=type('Req', (), {'session_id': 's1', 'message_id': 1, 'message_text': '수정 구현 진행'})(),
            thought_view=thought_view,
            contradiction_signals=[],
            trust_updates=[],
            revision_actions=[],
        )
        self.assertEqual(conclusion.inferred_intent, 'open_information_request')

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

    def test_search_sidecar_uses_question_form_and_graph_sparsity(self):
        sidecar = SearchSidecar()
        conclusion = CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='test',
            inferred_intent='open_information_request',
            activated_concepts=[],
            key_relations=[],
        )
        self.assertTrue(sidecar.should_search('이건 뭐야?', conclusion))
        self.assertFalse(sidecar.should_search('이건 뭐야', conclusion))

    def test_input_segmenter_has_no_keyword_sentence_kind(self):
        segmenter = InputSegmenter(hash_resolver=HashResolver())
        blocks = segmenter.segment('수정 구현 진행')
        self.assertEqual(blocks[0].block_kind, 'statement_phrase')


if __name__ == '__main__':
    unittest.main()
