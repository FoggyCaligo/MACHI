import unittest

from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.activation.pattern_detector import PatternDetector
from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.subgraph_pattern import PatternMatch, SubgraphPattern
from core.entities.thought_view import ThoughtView


class TestActivationEngineIntegration(unittest.TestCase):
    """Integration tests for ActivationEngine with PatternDetector."""

    def test_pattern_detector_integration(self):
        """Test that PatternDetector integrates correctly with ThoughtView."""
        # Create a ThoughtView with some nodes and edges
        thought_view = ThoughtView(
            session_id="test_session",
            message_text="test message",
            nodes=[
                Node(id=1, raw_value='Node 1'),
                Node(id=2, raw_value='Node 2'),
                Node(id=3, raw_value='Node 3')
            ],
            edges=[
                Edge(id=1, source_node_id=1, target_node_id=2, edge_family='relation', connect_type='flow', relation_detail={'connect_semantics': 'connects'}),
                Edge(id=2, source_node_id=2, target_node_id=3, edge_family='relation', connect_type='flow', relation_detail={'connect_semantics': 'connects'})
            ]
        )

        # Create pattern detector
        detector = PatternDetector()

        # Detect patterns
        patterns = detector.detect_patterns(thought_view)

        # Verify patterns were detected
        self.assertGreater(len(patterns), 0)
        self.assertIsInstance(patterns[0], PatternMatch)
        self.assertEqual(patterns[0].pattern.pattern_type, 'chain')
        self.assertEqual(patterns[0].matched_node_ids, [1, 2, 3])

    def test_conflict_resolution_policy_integration(self):
        """Test that conflict resolution policy works correctly."""
        from core.policies.conflict_resolution_policy import ConflictResolutionPolicy, ConflictResolutionStrategy

        # Create policy
        policy = ConflictResolutionPolicy(
            strategy=ConflictResolutionStrategy.HIGHEST_TRUST,
            trust_threshold=0.5
        )

        # Create competing patterns
        pattern1 = PatternMatch(
            pattern_id=1,
            pattern=SubgraphPattern(
                pattern_uid="pattern1",
                pattern_type="chain",
                node_ids=[1, 2, 3],
                edge_ids=[1, 2],
                topology_hash="hash1",
                cardinality=3,
                edge_count=2,
                pattern_trust=0.8
            ),
            match_score=0.8,
            matched_node_ids=[1, 2, 3],
            matched_edge_ids=[1, 2]
        )

        pattern2 = PatternMatch(
            pattern_id=2,
            pattern=SubgraphPattern(
                pattern_uid="pattern2",
                pattern_type="chain",
                node_ids=[1, 2, 3],
                edge_ids=[1, 2],
                topology_hash="hash1",
                cardinality=3,
                edge_count=2,
                pattern_trust=0.6
            ),
            match_score=0.6,
            matched_node_ids=[1, 2, 3],
            matched_edge_ids=[1, 2]
        )

        # Test conflict resolution
        resolved = policy.resolve_node_conflicts([pattern1, pattern2])

        # Should keep the higher trust pattern
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].pattern.pattern_trust, 0.8)

    def test_activation_engine_initialization(self):
        """Test that ActivationEngine initializes with PatternDetector."""
        # Mock UOW factory
        def mock_uow_factory():
            return None

        # Create engine
        engine = ActivationEngine(uow_factory=mock_uow_factory)

        # Verify PatternDetector is initialized
        self.assertIsInstance(engine.pattern_detector, PatternDetector)

    def test_thought_view_with_activated_patterns(self):
        """Test that ThoughtView can hold activated patterns."""
        thought_view = ThoughtView(
            session_id="test_session",
            message_text="test message"
        )

        # Initially empty
        self.assertEqual(len(thought_view.activated_patterns), 0)

        # Add patterns
        pattern = PatternMatch(
            pattern_id=1,
            pattern=SubgraphPattern(
                pattern_uid="test_pattern",
                pattern_type="chain",
                node_ids=[1, 2, 3],
                edge_ids=[1, 2],
                topology_hash="hash1",
                cardinality=3,
                edge_count=2,
                pattern_trust=0.8
            ),
            match_score=0.8,
            matched_node_ids=[1, 2, 3],
            matched_edge_ids=[1, 2]
        )

        thought_view.activated_patterns = [pattern]

        # Verify
        self.assertEqual(len(thought_view.activated_patterns), 1)
        self.assertEqual(thought_view.activated_patterns[0].pattern.pattern_type, 'chain')


if __name__ == '__main__':
    unittest.main()
