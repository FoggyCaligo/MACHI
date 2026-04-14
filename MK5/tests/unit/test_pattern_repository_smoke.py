"""
Smoke test for SqlitePatternRepository.

Validates basic operations: create, retrieve, update, conflict tracking.
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.subgraph_pattern import SubgraphPattern
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def test_pattern_repository_smoke() -> None:
    """Test basic CRUD and conflict operations on patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        schema_path = ROOT / "storage" / "schema.sql"

        # Initialize database
        with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True) as uow:
            uow.patterns.ping()

        # Test 1: Create a pattern
        with SqliteUnitOfWork(db_path) as uow:
            pattern = SubgraphPattern(
                pattern_uid="pat_001",
                pattern_type="chain",
                node_ids=[1, 2, 3],
                edge_ids=[10, 11],
                topology_hash="hash_abc123",
                cardinality=3,
                edge_count=2,
                pattern_trust=0.7,
                backing_evidence_count=5,
            )
            stored = uow.patterns.add(pattern)
            assert stored.id is not None
            pattern_id = stored.id
            uow.commit()

        # Test 2: Retrieve pattern by id
        with SqliteUnitOfWork(db_path) as uow:
            retrieved = uow.patterns.get_by_id(pattern_id)
            assert retrieved is not None
            assert retrieved.pattern_uid == "pat_001"
            assert retrieved.pattern_type == "chain"
            assert retrieved.cardinality == 3
            assert retrieved.pattern_trust == 0.7

        # Test 3: Retrieve by uid
        with SqliteUnitOfWork(db_path) as uow:
            retrieved = uow.patterns.get_by_uid("pat_001")
            assert retrieved is not None
            assert retrieved.id == pattern_id

        # Test 4: Retrieve by topology hash
        with SqliteUnitOfWork(db_path) as uow:
            retrieved = uow.patterns.get_by_topology_hash("hash_abc123")
            assert retrieved is not None
            assert retrieved.id == pattern_id

        # Test 5: Bump backing evidence (confirmation)
        with SqliteUnitOfWork(db_path) as uow:
            uow.patterns.bump_backing_evidence(pattern_id, delta=2, trust_delta=0.1)
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            updated = uow.patterns.get_by_id(pattern_id)
            assert updated is not None
            assert updated.backing_evidence_count == 7
            assert abs(updated.pattern_trust - 0.8) < 0.001

        # Test 6: Bump conflict (contradiction)
        with SqliteUnitOfWork(db_path) as uow:
            uow.patterns.bump_conflict(pattern_id, delta=1, pressure_delta=1.5, trust_delta=-0.1)
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            updated = uow.patterns.get_by_id(pattern_id)
            assert updated is not None
            assert updated.conflict_count == 1
            assert abs(updated.conflict_pressure - 1.5) < 0.001
            assert abs(updated.pattern_trust - 0.7) < 0.001

        # Test 7: Set as revision candidate
        with SqliteUnitOfWork(db_path) as uow:
            uow.patterns.set_revision_candidate(pattern_id, flag=True)
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            updated = uow.patterns.get_by_id(pattern_id)
            assert updated is not None
            assert updated.revision_candidate_flag is True

        # Test 8: List revision candidates
        with SqliteUnitOfWork(db_path) as uow:
            candidates = uow.patterns.list_revision_candidates(min_conflict_pressure=1.0)
            assert len(candidates) > 0
            assert any(c.id == pattern_id for c in candidates)

        # Test 9: List active patterns
        with SqliteUnitOfWork(db_path) as uow:
            active = uow.patterns.list_active_patterns(pattern_types=["chain"])
            assert len(active) > 0
            assert any(p.id == pattern_id for p in active)

        # Test 10: Deactivate pattern
        with SqliteUnitOfWork(db_path) as uow:
            uow.patterns.deactivate(pattern_id)
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            updated = uow.patterns.get_by_id(pattern_id)
            assert updated is not None
            assert updated.is_active is False

        print("✅ All pattern repository smoke tests passed")


if __name__ == "__main__":
    test_pattern_repository_smoke()
