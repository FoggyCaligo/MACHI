from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from core.thinking.revision_rule_analytics import RevisionRuleSuggestion

PRESET_DELTAS: dict[str, float] = {
    'conservative': 0.45,
    'balanced': 0.25,
    'aggressive': 0.12,
}


def build_rule_overrides_from_suggestions(
    suggestions: list[RevisionRuleSuggestion] | list[dict[str, Any]],
    *,
    preset: str = 'balanced',
) -> dict[str, dict[str, float]]:
    step = PRESET_DELTAS.get(str(preset or '').strip().lower(), PRESET_DELTAS['balanced'])
    overrides: dict[str, dict[str, float]] = {}
    for item in suggestions:
        payload = _as_dict(item)
        rule_name = ' '.join(str(payload.get('rule_name') or '').split()).strip()
        recommendation = ' '.join(str(payload.get('recommendation') or '').split()).strip()
        if not rule_name or not recommendation:
            continue
        target = overrides.setdefault(rule_name, {})
        _apply_recommendation(target, recommendation=recommendation, step=step)
    return overrides


def _apply_recommendation(target: dict[str, float], *, recommendation: str, step: float) -> None:
    if recommendation == 'raise_deactivate_evidence_threshold':
        _increase(target, 'marker_conflict_evidence_threshold_for_deactivate', step)
        _increase(target, 'marker_deactivate_evidence_threshold', step * 0.8)
        return
    if recommendation == 'lower_deactivate_evidence_threshold':
        _decrease(target, 'marker_conflict_evidence_threshold_for_deactivate', step)
        _decrease(target, 'marker_deactivate_evidence_threshold', step * 0.8)
        return
    if recommendation == 'raise_merge_evidence_threshold':
        _increase(target, 'marker_merge_evidence_threshold', step)
        _increase(target, 'marker_conflict_evidence_threshold_for_merge', step * 0.7)
        return
    if recommendation == 'lower_merge_evidence_threshold':
        _decrease(target, 'marker_merge_evidence_threshold', step)
        _decrease(target, 'marker_conflict_evidence_threshold_for_merge', step * 0.7)


def _increase(target: dict[str, float], key: str, delta: float) -> None:
    base = _baseline_for_key(key, current=target.get(key))
    target[key] = round(max(0.05, base + delta), 6)


def _decrease(target: dict[str, float], key: str, delta: float) -> None:
    base = _baseline_for_key(key, current=target.get(key))
    target[key] = round(max(0.05, base - delta), 6)


def _as_dict(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if is_dataclass(item):
        return dict(asdict(item))
    return {}


def _baseline_for_key(key: str, *, current: object) -> float:
    if current is not None:
        try:
            return float(current)
        except (TypeError, ValueError):
            pass
    token = str(key or '').strip()
    if token == 'marker_conflict_evidence_threshold_for_deactivate':
        return 2.2
    if token == 'marker_deactivate_evidence_threshold':
        return 2.6
    if token == 'marker_conflict_evidence_threshold_for_merge':
        return 3.0
    if token == 'marker_merge_evidence_threshold':
        return 3.6
    return 1.0
