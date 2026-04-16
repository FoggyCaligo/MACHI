#!/usr/bin/env python3
"""One-time migration: rename old identity anchor keys in the nodes table.

Why this is needed
------------------
graph_ingest_service._identity_anchor_key() previously returned semantically
loaded labels ('user_self', 'assistant_self', 'search_source_self').  These
have been replaced with neutral technical labels ('participant_user',
'participant_assistant', 'participant_search') so that concept differentiation
can later infer meaningful edges (e.g. participant_user → person) from graph
structure rather than from embedded label semantics.

Because the address_hash of each anchor node is derived from (session_id,
anchor_key), renaming the key also changes the hash.  This script rewrites
both the address_hash and the payload in place.

Usage
-----
    python scripts/migrate_identity_anchors.py path/to/mk5.db

Dry-run (no writes):
    python scripts/migrate_identity_anchors.py path/to/mk5.db --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

# Must match HashResolver.digest_size (default = 16 → 32 hex chars)
DIGEST_SIZE = 16

RENAMES: dict[str, str] = {
    'user_self': 'participant_user',
    'assistant_self': 'participant_assistant',
    'search_source_self': 'participant_search',
}


def _address_hash(session_id: str, anchor_key: str) -> str:
    payload = f'identity_anchor::{session_id}::{anchor_key}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[: DIGEST_SIZE * 2]


def migrate(db_path: str | Path, *, dry_run: bool = False) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    updated = 0

    try:
        rows = conn.execute(
            'SELECT id, address_hash, raw_value, normalized_value, payload'
            ' FROM nodes WHERE is_active = 1'
        ).fetchall()

        for row in rows:
            payload_raw = row['payload']
            if not payload_raw:
                continue
            try:
                payload = json.loads(payload_raw)
            except Exception:
                continue

            old_key = str(payload.get('anchor_key') or '').strip()
            if old_key not in RENAMES:
                continue

            session_id = str(payload.get('session_id') or '').strip()
            new_key = RENAMES[old_key]
            new_hash = _address_hash(session_id, new_key)

            payload['anchor_key'] = new_key
            new_payload_raw = json.dumps(payload, ensure_ascii=False)

            print(
                f'  Node {row["id"]:>6}  {old_key!r:28} → {new_key!r}'
                f'  session={session_id[:12]!r}'
            )

            if not dry_run:
                conn.execute(
                    'UPDATE nodes'
                    ' SET address_hash = ?, raw_value = ?, normalized_value = ?, payload = ?'
                    ' WHERE id = ?',
                    (new_hash, new_key, new_key, new_payload_raw, row['id']),
                )
            updated += 1

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    mode = '[DRY-RUN] ' if dry_run else ''
    print(f'\n{mode}Done. {updated} anchor node(s) {"would be" if dry_run else "were"} updated.')
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('db_path', help='Path to the SQLite database file')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would change without writing anything',
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f'Error: database not found: {db_path}', file=sys.stderr)
        sys.exit(1)

    migrate(db_path, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
