"""app/batch/refresh_derived.py（改善計画T281段階2）の単体テスト。

各段（既存バッチのrun/run_match）を呼ぶ薄いオーケストレーションのため、実DBは使わず
各段をモックして呼び出し順序・引数の伝播・失敗時の停止だけを検証する。
"""

import pytest

from app.batch import refresh_derived


def _record_calls(monkeypatch, calls: list[str], *, fail_at: str | None = None):
    async def _fake(label: str, database_url, dry_run):
        calls.append(label)
        if label == fail_at:
            raise RuntimeError(f"{label} failed")
        return 0

    for label, module in [
        ("④presplit_road_graph", refresh_derived.presplit_road_graph),
        ("⑤precompute_road_node_degrees", refresh_derived.precompute_road_node_degrees),
        ("⑥precompute_edge_attribute_counts", refresh_derived.precompute_edge_attribute_counts),
        ("⑦precompute_elevation_attributes", refresh_derived.precompute_elevation_attributes),
        ("⑧precompute_way_attribute_counts", refresh_derived.precompute_way_attribute_counts),
    ]:
        monkeypatch.setattr(
            module, "run", lambda db, dr, _label=label: _fake(_label, db, dr)
        )
    monkeypatch.setattr(
        refresh_derived.match_designations,
        "run_match",
        lambda db, dr: _fake("⑨match_designations", db, dr),
    )


async def test_run_calls_all_stages_in_dependency_order(monkeypatch):
    calls: list[str] = []
    _record_calls(monkeypatch, calls)

    result = await refresh_derived.run(database_url=None, dry_run=False)

    assert result == 0
    assert calls == [
        "④presplit_road_graph",
        "⑤precompute_road_node_degrees",
        "⑥precompute_edge_attribute_counts",
        "⑦precompute_elevation_attributes",
        "⑧precompute_way_attribute_counts",
        "⑨match_designations",
    ]


async def test_run_propagates_database_url_and_dry_run_to_every_stage(monkeypatch):
    seen: list[tuple[str, object, bool]] = []

    async def _fake(label: str, database_url, dry_run):
        seen.append((label, database_url, dry_run))
        return 0

    for label, module in [
        ("presplit", refresh_derived.presplit_road_graph),
        ("degrees", refresh_derived.precompute_road_node_degrees),
        ("edge_counts", refresh_derived.precompute_edge_attribute_counts),
        ("elevation", refresh_derived.precompute_elevation_attributes),
        ("way_counts", refresh_derived.precompute_way_attribute_counts),
    ]:
        monkeypatch.setattr(module, "run", lambda db, dr, _label=label: _fake(_label, db, dr))
    monkeypatch.setattr(
        refresh_derived.match_designations, "run_match", lambda db, dr: _fake("match", db, dr)
    )

    await refresh_derived.run(database_url="postgresql://example", dry_run=True)

    assert seen == [
        (label, "postgresql://example", True)
        for label in ["presplit", "degrees", "edge_counts", "elevation", "way_counts", "match"]
    ]


async def test_run_stops_immediately_when_a_stage_fails(monkeypatch):
    calls: list[str] = []
    _record_calls(monkeypatch, calls, fail_at="⑥precompute_edge_attribute_counts")

    with pytest.raises(RuntimeError, match="⑥precompute_edge_attribute_counts failed"):
        await refresh_derived.run(database_url=None, dry_run=False)

    # ④⑤⑥までは呼ばれ、⑥の失敗で⑦⑧⑨は呼ばれない（fail-fast、部分的に古いデータの
    # まま後続段が進むのを避ける設計）。
    assert calls == ["④presplit_road_graph", "⑤precompute_road_node_degrees", "⑥precompute_edge_attribute_counts"]
