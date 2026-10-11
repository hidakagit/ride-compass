"""通行方向の段（`batch/derive_way_directions.py`）が、通行方向を持たない道を残したまま書き終えないこと。

通行方向の無い道の区間は、探索が両方向に通れる枝として組む——一方通行を逆走するルートが出る。

ここで見ないもの: 上下線が分かれた道の片側かの判定 → `test_derive_divided.py`。タグから通行方向を決める規則
→ `test_resolve_direction.py`。
"""

import pytest

from app.batch import derive_topology, derive_way_directions
from tests.source_ingest import ingest_records, way_record, zigzag_point

# road_graph_session（conftest.py）と同じDBを使うため、.claude/rules/testing.mdのパターン2どおり
# loop_scope="module"が必須。
pytestmark = pytest.mark.asyncio(loop_scope="module")

ONEWAY = {"highway": "residential", "oneway": "yes"}


def _way(way_id: int, node_ids: list[int]):
    return way_record(way_id, [zigzag_point(n) for n in node_ids], node_ids, ONEWAY)


async def test_the_stage_stops_when_a_way_of_the_network_gets_no_direction(derive_conn):
    """区間を切った後に道の生データが1本欠けると（区間を切る段を飛ばして流した場面）、その道の通行方向が決まらず、
    段は数の食い違いで止まる。欠けていなければ書き終える。"""
    await ingest_records("osm_way", [_way(100, [1, 2]), _way(200, [2, 3])], conn=derive_conn)
    await derive_topology.derive(derive_conn)
    await derive_way_directions.derive(derive_conn)
    await ingest_records("osm_way", [_way(100, [1, 2])], conn=derive_conn)

    with pytest.raises(RuntimeError, match="通行方向を持たない道がある: 道 2本に対して通行方向 1本"):
        await derive_way_directions.derive(derive_conn)
