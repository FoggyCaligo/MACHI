from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.thinking.revision_rule_analytics import aggregate_revision_rule_events, recommend_rule_adjustments
from core.thinking.revision_rule_tuner import PRESET_DELTAS, build_rule_overrides_from_suggestions
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Summarize revision-rule event behavior from graph_events.')
    parser.add_argument('--db', type=str, default='data/memory.db', help='Path to SQLite DB')
    parser.add_argument('--schema', type=str, default='storage/schema.sql', help='Path to schema.sql')
    parser.add_argument('--limit', type=int, default=2000, help='Max recent graph events to scan')
    parser.add_argument('--json', action='store_true', help='Print report as JSON')
    parser.add_argument('--suggest', action='store_true', help='Include threshold tuning suggestions')
    parser.add_argument(
        '--preset',
        type=str,
        default='balanced',
        choices=sorted(PRESET_DELTAS.keys()),
        help='Preset intensity for suggested override values',
    )
    parser.add_argument('--overrides-out', type=str, default='', help='Optional path to write suggested rule override JSON')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    schema_path = Path(args.schema)
    with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=False) as uow:
        events = list(uow.graph_events.list_recent(limit=max(1, int(args.limit))))
    rows = aggregate_revision_rule_events(events)
    payload = [row.to_dict() for row in rows]
    suggestions = [item.to_dict() for item in recommend_rule_adjustments(rows)] if args.suggest else []
    overrides = build_rule_overrides_from_suggestions(suggestions, preset=args.preset) if args.suggest else {}

    if args.overrides_out:
        out_path = Path(args.overrides_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding='utf-8')

    if args.json:
        result = {'report': payload}
        if args.suggest:
            result['suggestions'] = suggestions
            result['preset'] = args.preset
            result['overrides'] = overrides
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not payload:
        print('No revision-rule events found.')
        return

    print('Revision Rule Report')
    print('====================')
    for row in payload:
        print(
            f"[{row['rule_name']}] total={row['total_count']} "
            f"pending={row['pending_count']} deactivated={row['deactivated_count']} merged={row['merged_count']} "
            f"avg_conflict_evd={row['avg_conflict_evidence']:.3f} "
            f"avg_deactivate_evd={row['avg_deactivate_evidence']:.3f} "
            f"avg_merge_evd={row['avg_merge_evidence']:.3f}"
        )
    if args.suggest:
        print()
        print('Suggestions')
        print('-----------')
        if not suggestions:
            print('No threshold suggestions from current sample.')
        for item in suggestions:
            print(
                f"[{item['rule_name']}] {item['recommendation']} "
                f"(confidence={item['confidence']}) - {item['rationale']}"
            )
        print()
        print(f'Preset: {args.preset}')
        print('Suggested Overrides')
        print('-------------------')
        if not overrides:
            print('No overrides generated.')
        else:
            print(json.dumps(overrides, ensure_ascii=False, indent=2))
        if args.overrides_out:
            print()
            print(f'Overrides written to: {args.overrides_out}')


if __name__ == '__main__':
    main()
