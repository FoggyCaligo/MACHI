from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.thinking.revision_rule_analytics import aggregate_revision_rule_events, recommend_rule_adjustments
from core.thinking.revision_rule_tuner import PRESET_DELTAS, build_rule_overrides_from_suggestions
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Generate and apply revision-rule override JSON from graph event history.'
    )
    parser.add_argument('--db', type=str, default='data/memory.db', help='Path to SQLite DB')
    parser.add_argument('--schema', type=str, default='storage/schema.sql', help='Path to schema.sql')
    parser.add_argument('--limit', type=int, default=2000, help='Max recent graph events to scan')
    parser.add_argument(
        '--preset',
        type=str,
        default='balanced',
        choices=sorted(PRESET_DELTAS.keys()),
        help='Preset intensity for generated override values',
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/revision_rule_overrides.auto.json',
        help='Output path for applied overrides',
    )
    parser.add_argument(
        '--mode',
        type=str,
        default='merge',
        choices=['merge', 'replace'],
        help='merge: preserve existing overrides and overlay generated values, replace: overwrite with generated values',
    )
    parser.add_argument('--dry-run', action='store_true', help='Do not write output file')
    parser.add_argument('--json', action='store_true', help='Print machine-readable JSON result')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    schema_path = Path(args.schema)
    output_path = Path(args.output)

    with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=False) as uow:
        events = list(uow.graph_events.list_recent(limit=max(1, int(args.limit))))

    aggregates = aggregate_revision_rule_events(events)
    suggestions = recommend_rule_adjustments(aggregates)
    generated = build_rule_overrides_from_suggestions(suggestions, preset=args.preset)
    existing = _load_existing(output_path)
    applied = _merge_overrides(existing, generated) if args.mode == 'merge' else generated

    if not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(applied, ensure_ascii=False, indent=2), encoding='utf-8')

    result = {
        'db': str(db_path),
        'output': str(output_path),
        'mode': args.mode,
        'preset': args.preset,
        'dry_run': bool(args.dry_run),
        'aggregate_count': len(aggregates),
        'suggestion_count': len(suggestions),
        'generated_rule_count': len(generated),
        'existing_rule_count': len(existing),
        'applied_rule_count': len(applied),
        'generated_overrides': generated,
        'applied_overrides': applied,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print('Revision Rule Override Apply')
    print('============================')
    print(f"db={result['db']}")
    print(f"output={result['output']}")
    print(f"mode={result['mode']} preset={result['preset']} dry_run={result['dry_run']}")
    print(
        'aggregates={aggregate_count} suggestions={suggestion_count} generated={generated_rule_count} '
        'existing={existing_rule_count} applied={applied_rule_count}'.format(**result)
    )
    if not generated:
        print('generated_overrides: none')
    else:
        print('generated_overrides:')
        print(json.dumps(generated, ensure_ascii=False, indent=2))
    if args.mode == 'merge' and existing:
        print('existing_overrides:')
        print(json.dumps(existing, ensure_ascii=False, indent=2))
    print('applied_overrides:')
    print(json.dumps(applied, ensure_ascii=False, indent=2))
    if not args.dry_run:
        print()
        print(f'Wrote: {output_path}')
        print(f'Set env: REVISION_RULE_OVERRIDES_PATH={output_path}')


def _load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for rule_name, value in payload.items():
        if not isinstance(value, dict):
            continue
        name = ' '.join(str(rule_name or '').split()).strip()
        if not name:
            continue
        result[name] = {str(key): item for key, item in value.items()}
    return result


def _merge_overrides(
    existing: dict[str, dict[str, Any]],
    generated: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {rule_name: dict(values) for rule_name, values in existing.items()}
    for rule_name, values in generated.items():
        target = merged.setdefault(rule_name, {})
        target.update(dict(values))
    return merged


if __name__ == '__main__':
    main()
