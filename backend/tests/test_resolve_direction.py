"""通行方向の引き当て（`domain/traffic.py: direction_sql`）。

タグの生値から「どちら向きに走れるか」を決める判断で、派生バッチ（`derive_way_materials`）
だけが使う。結果は`way_materials.direction`に入り、探索が逆向きの枝を作ってよいかを決める。

**判定はDB側で行うため、DBへ通して確かめる。**規則の表だけを見て通るテストにすると、
表が実際にどう引き当てられるか（優先順位・値の正規化）を押さえられない。
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.traffic import direction_sql

# road_graph_session（conftest.py）はファイル単位でエンジン・イベントループを共有する設計
# のため、docs/conventions/testing.mdのパターン2どおりloop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def resolve(session: AsyncSession, tags: dict) -> str:
    literal = "'" + json.dumps(tags, ensure_ascii=False).replace("'", "''") + "'"
    sql = direction_sql(f"SELECT 1 AS id, {literal}::jsonb AS tags")
    return (await session.execute(text(sql))).one().direction


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "residential"}, "both"),
        ({"oneway": "yes"}, "forward"),
        ({"oneway": "-1"}, "backward"),
        # 前後の空白と大文字小文字は正規化する。
        ({"oneway": " YES "}, "forward"),
        # 時間帯で向きが変わる値は両方向として扱う（時刻を持たない列では表せない）。
        ({"oneway": "alternating"}, "both"),
    ],
)
async def test_oneway_tag(road_graph_session, tags, expected):
    assert await resolve(road_graph_session, tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # 車は一方通行だが自転車は逆走可（contraflow cycling）の代表例。
        ({"oneway": "yes", "oneway:bicycle": "no"}, "both"),
        ({"oneway": "-1", "oneway:bicycle": "yes"}, "forward"),
        ({"oneway": "yes", "oneway:bicycle": "-1"}, "backward"),
        ({"oneway": "yes", "oneway:bicycle": " NO "}, "both"),
        # 解釈できない値のときだけ`oneway`本体へ落ちる。
        ({"oneway": "yes", "oneway:bicycle": "alternating"}, "forward"),
    ],
)
async def test_oneway_bicycle_wins_over_oneway(road_graph_session, tags, expected):
    assert await resolve(road_graph_session, tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # 環状交差点は構造として一方向にしか通れず、OSMは個々のwayへonewayを付けない慣行が
        # ある。両方向として扱うと、探索が環を逆走する経路を出しうる。
        ({"highway": "tertiary", "junction": "roundabout"}, "forward"),
        ({"highway": "tertiary", "junction": "circular"}, "forward"),
        # OSM側が「両方向」と言っているなら、構造からの推定より優先する。
        ({"highway": "tertiary", "junction": "roundabout", "oneway": "no"}, "both"),
        ({"highway": "tertiary", "junction": "roundabout", "oneway": "-1"}, "backward"),
        # 構造として一方向を含意しない値まで一方通行にしない。
        ({"highway": "tertiary", "junction": "yes"}, "both"),
    ],
)
async def test_junction_implies_one_way_only_when_oneway_is_absent(
    road_graph_session, tags, expected
):
    assert await resolve(road_graph_session, tags) == expected
