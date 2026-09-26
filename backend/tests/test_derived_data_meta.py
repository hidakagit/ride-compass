"""`infrastructure/derived_data_meta.py`——派生データの世代。

世代の変化を読み手がどう使うか（キャッシュの追随・配列の作り直し）は、それぞれの読み手のテストが持つ。
入れ替えと同じトランザクションで進むことは`test_derive_cli.py`が見る。
"""

import asyncpg
import pytest

from app.batch._common import asyncpg_dsn
from app.infrastructure import derived_data_meta
from tests.conftest import postgis_database_url

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def test_first_bump_creates_the_revision_and_later_bumps_advance_it(road_graph_session):
    """行が無いDB（スキーマをORMの宣言から作っただけ）でも、最初に進めた時点で世代が生まれる。"""
    assert await derived_data_meta.get_revision(road_graph_session) is None

    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        first = await derived_data_meta.bump_revision(conn)
        second = await derived_data_meta.bump_revision(conn)
    finally:
        await conn.close()

    assert (first, second) == (1, 2)
    assert await derived_data_meta.get_revision(road_graph_session) == 2
