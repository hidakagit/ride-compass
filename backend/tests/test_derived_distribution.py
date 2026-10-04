"""派生の値の分布（`scripts/derived_distribution.py`）が、列の型ごとに分布を1行で出すこと。"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from derived_distribution import collect, select_targets  # noqa: E402
from tests.conftest import postgis_database_url  # noqa: E402

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: (種別, 枝の本数, 信号)
NODES = (("traffic_signals", 0, True), ("traffic_signals", 2, False), (None, 3, False), ("crossing", 3, False))


async def _insert_nodes(session) -> None:
    for node_id, (kind, branch_count, signals) in enumerate(NODES, start=1):
        await session.execute(text(
            "INSERT INTO node_materials (osm_node_id, kind, branch_count, has_traffic_signals)"
            " VALUES (:id, :kind, :branch_count, :signals)"),
            {"id": node_id, "kind": kind, "branch_count": branch_count, "signals": signals})
    await session.commit()


async def test_each_column_type_gets_its_own_summary(road_graph_session):
    await _insert_nodes(road_graph_session)

    lines = await collect(postgis_database_url(), select_targets(
        ["node_materials.branch_count", "node_materials.has_traffic_signals", "node_materials.kind"]))

    # 行の並びは宣言の列の順（引数の順ではない）。
    assert lines == [
        "node_materials.kind: 行 4 / 値あり 75.0% / 種類 2",
        # 分位は線形補間: [0, 2, 3, 3] の p10 は 0 と 2 の間の 0.3、p50 は 2 と 3 の間の 0.5。
        "node_materials.branch_count: 行 4 / 値あり 100.0% / 0でない 75.0% / 合計 8"
        " / p10 0.6 / p50 2.5 / p90 3 / 最大 3",
        "node_materials.has_traffic_signals: 行 4 / 値あり 100.0% / 真 25.0%",
    ]


async def test_every_declared_value_column_is_measured_even_when_empty(road_graph_session):
    targets = select_targets([])

    lines = await collect(postgis_database_url(), targets)

    assert [line.split(":")[0] for line in lines] == [f"{t.table}.{t.column}" for t in targets]
    assert all("値あり -" in line for line in lines)


async def test_a_name_that_is_not_a_declared_value_column_is_refused():
    with pytest.raises(SystemExit, match="osm_node_id"):
        select_targets(["node_materials.osm_node_id"])

