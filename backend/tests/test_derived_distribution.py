"""派生の値の分布（`scripts/derived_distribution.py`）が、列の型ごとに分布を1行で出すこと。

測る値は、生データを取り込んで派生の段を本物のまま流して作る。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.batch import derive_node_materials, derive_topology  # noqa: E402
from app.domain.tuning import TUNING_PARAMETERS_BY_ID  # noqa: E402
from derived_distribution import collect, select_targets  # noqa: E402
from tests.conftest import postgis_database_url, raw_connection  # noqa: E402
from tests.source_ingest import ingest_records, point_record, way_record  # noqa: E402

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: ノード → (経度, 緯度, タグ)。0.001度は約90mで、信号とみなす半径より遠い。9はどの道にも属さない店。
NODES = {1: (139.700, 35.68, {}), 2: (139.701, 35.68, {"highway": "traffic_signals"}), 3: (139.702, 35.68, {}),
         4: (139.701, 35.681, {}), 9: (139.705, 35.685, {"shop": "convenience"})}
#: 道100はノード2で道200と交わり、2区間に切れる。
WAYS = {100: [1, 2, 3], 200: [2, 4]}


async def _derive_nodes() -> None:
    await ingest_records("osm_way", [
        way_record(way_id, [NODES[n][:2] for n in node_ids], node_ids) for way_id, node_ids in WAYS.items()])
    await ingest_records("osm_node", [point_record(n, lon, lat, tags) for n, (lon, lat, tags) in NODES.items()])
    async with raw_connection() as conn:
        await derive_topology.derive(conn)
        await derive_node_materials.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)


async def test_each_column_type_gets_its_own_summary(road_graph_session):
    await _derive_nodes()

    lines = await collect(postgis_database_url(), select_targets(
        ["node_materials.branch_count", "node_materials.has_traffic_signals", "node_materials.kind"]))

    # 行の並びは宣言の列の順（引数の順ではない）。
    assert lines == [
        "node_materials.kind: 行 5 / 値あり 40.0% / 種類 2",
        # 枝の本数は [0, 1, 1, 1, 3]。分位は線形補間: p10 は 0 と 1 の間の 0.4、p90 は 1 と 3 の間の 0.6。
        "node_materials.branch_count: 行 5 / 値あり 100.0% / 0でない 80.0% / 合計 6"
        " / p10 0.4 / p50 1 / p90 2.2 / 最大 3",
        "node_materials.has_traffic_signals: 行 5 / 値あり 100.0% / 真 20.0%",
    ]


async def test_every_declared_value_column_is_measured_even_when_empty(road_graph_session):
    targets = select_targets([])

    lines = await collect(postgis_database_url(), targets)

    assert [line.split(":")[0] for line in lines] == [f"{t.table}.{t.column}" for t in targets]
    assert all("値あり -" in line for line in lines)


async def test_a_name_that_is_not_a_declared_value_column_is_refused():
    with pytest.raises(SystemExit, match="osm_node_id"):
        select_targets(["node_materials.osm_node_id"])

