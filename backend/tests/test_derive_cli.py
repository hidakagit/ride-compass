"""派生の作り直し（`batch/derive_cli.py`）が、できあがるまで読み手に途中の状態を見せないこと。

段そのものの値の出し方は段ごとのテスト（`test_derive_*.py`）が持つ。ここは入口が負う契約——
作業用のスキーマで作り、1つのトランザクションで入れ替え、世代を進め、その中身から作った道路網を置く・
作った取込を記録し、生データか派生の表の列が記録から変わっていれば途中から流さない・取込と同時に走らない・
管理画面で変えた較正値を段へ渡す——を見る。
段は本物を通し、読み手の目で見るための覗き窓だけを段の後ろに挟む。
見ないもの: 取込の間に作り直しが止まること → `test_ingest.py`。
"""

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch import derive_cli
from app.batch.source_adapters.npa_honhyo import HonhyoRows
from app.domain.accident import PartyType
from app.domain.material_catalog import ACCIDENT_COUNT_PER_KM_YEAR
from app.infrastructure import derived_data_meta, road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.source_models import PARTY_TYPE_CODES
from tests.conftest import postgis_database_url, raw_connection
from tests.source_ingest import abr_prefecture_record, ingest_records, point_record, way_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
STEP = 0.001

#: (道, 参照ノード列, タグ)。道100を一方通行にして取り直すと、作り直しで通行方向が変わる。
WAYS = (
    (100, [1, 2, 3], {"highway": "residential"}),
    (200, [3, 4], {"highway": "residential"}),
)
ONEWAY = {"oneway": "yes"}
DERIVED = ("edge_materials", "way_materials", "road_edges", "node_materials")


def _point(node_id: int) -> tuple[float, float]:
    return (BASE_LON + STEP * node_id, BASE_LAT + STEP * (node_id % 2))


_STRUCTURE_SQL = """
SELECT 'index' AS kind, tablename AS table_name, indexname AS name, indexdef AS definition
FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY($1::text[])
UNION ALL
SELECT 'constraint', r.relname, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace
WHERE n.nspname = 'public' AND r.relname = ANY($1::text[])
ORDER BY 1, 2, 3
"""


async def _ingest_ways(conn: asyncpg.Connection, way_100_tags: dict[str, str] | None = None) -> int:
    """`WAYS`を取り込み、`run_id`を返す。`way_100_tags`は道100のタグに足す。"""
    return await ingest_records("osm_way", [
        way_record(way_id, [_point(n) for n in node_ids], node_ids,
                   {**tags, **(way_100_tags or {})} if way_id == 100 else tags)
        for way_id, node_ids, tags in WAYS], conn=conn)


async def _ingest_addresses(conn: asyncpg.Connection) -> int:
    """住所の生データ（都道府県1つ）を取り込み、`run_id`を返す。住所の段は`abr`の取込が無いと止まる。"""
    return await ingest_records("abr", [abr_prefecture_record("130001", "東京都", *_point(1))], conn=conn)


async def _schemas(conn: asyncpg.Connection) -> set[str]:
    """一時の表のスキーマ（接続ごとに作られ、残る）を除いたスキーマ。作り直しが作業用のスキーマを残さないことを見る。"""
    return {row["nspname"] for row in await conn.fetch(
        "SELECT nspname FROM pg_namespace"
        " WHERE nspname NOT LIKE 'pg\\_temp\\_%' AND nspname NOT LIKE 'pg\\_toast\\_temp\\_%'")}


async def _revision(conn: asyncpg.Connection) -> int | None:
    return await conn.fetchval("SELECT revision FROM derived_data_meta")


@pytest_asyncio.fixture(loop_scope="module")
async def schemas_at_start(road_graph_engine) -> set[str]:
    """作り直しを1度も走らせる前のスキーマ。作り直しが作業用のスキーマを残さないことは、これと比べて見る。"""
    async with raw_connection() as conn:
        return await _schemas(conn)


@pytest_asyncio.fixture(loop_scope="module")
async def derived_before(road_graph_engine, schemas_at_start, road_network_root):
    """作り直す前の状態: 今の生データから最初の段まで作り直し、世代1の表と道路網がある。道路網の置き場は一時ディレクトリ（`road_network_root`）。

    `road_graph_engine`に依存するのはスキーマを作らせるため。
    """
    async with raw_connection() as conn:
        try:
            await conn.execute("TRUNCATE " + ", ".join(DERIVED) + ", source_features, source_runs, derived_data_meta CASCADE")
            await ingest_records("osm_node", [point_record(n, *_point(n)) for n in range(1, 5)], conn=conn)
            await _ingest_ways(conn)
            await _ingest_addresses(conn)
            assert await derive_cli.run(postgis_database_url(), None) == 0
            yield conn
        finally:
            for left in await _schemas(conn) - schemas_at_start:
                await conn.execute(f'DROP SCHEMA "{left}" CASCADE')
            await conn.execute("TRUNCATE " + ", ".join(DERIVED) + ", source_features, source_runs, derived_data_meta CASCADE")


def _observe_after(stage_name: str, monkeypatch, observe) -> None:
    """段`stage_name`の後ろに覗き窓を挟む（段そのものは本物を通す）。"""
    real = dict(derive_cli.STAGES)[stage_name]

    async def stage_then_observe(conn, tuning):
        await real(conn, tuning)
        await observe()

    monkeypatch.setattr(derive_cli, "STAGES", tuple(
        (name, stage_then_observe if name == stage_name else stage) for name, stage in derive_cli.STAGES))


async def test_readers_see_the_previous_tables_until_the_swap_and_the_rebuilt_ones_after(
        derived_before, schemas_at_start, monkeypatch):
    """段が書き終えても、入れ替えまでは読み手は前の表を読む。入れ替えの後は、前から開いている接続の
    準備済みの文も作り直した表を読み、世代が1つ進み、その世代の道路網は作り直した表から作られている。"""
    structure_before = await derived_before.fetch(_STRUCTURE_SQL, list(DERIVED))
    await _ingest_ways(derived_before, ONEWAY)
    async with raw_connection() as reader:
        direction = await reader.prepare("SELECT direction FROM way_materials WHERE osm_way_id = $1")
        seen_while_rebuilding: list[tuple[str, int | None]] = []

        async def observe():
            seen_while_rebuilding.append((await direction.fetchval(100), await _revision(reader)))

        _observe_after("ways", monkeypatch, observe)

        assert await derive_cli.run(postgis_database_url(), None) == 0

        assert seen_while_rebuilding == [("both", 1)]
        assert await direction.fetchval(100) == "forward"
        assert await _revision(reader) == 2

    network = road_network_store.current()
    assert network.revision == 2
    directions = set(zip(network.edge_way_id.tolist(), network.edge_forward.tolist(), strict=True))
    assert (100, False) not in directions
    assert (200, False) in directions
    # 入れ替えた表は、前の表と同じ名前の索引・制約を持つ。
    assert await derived_before.fetch(_STRUCTURE_SQL, list(DERIVED)) == structure_before
    assert await _schemas(derived_before) == schemas_at_start


async def test_a_failed_rebuild_changes_nothing_readers_see(derived_before, schemas_at_start, monkeypatch):
    """途中で落ちたら、表も世代も道路網の置き場も前のまま。作業用のスキーマは残らない。"""
    network_before = sorted(road_network_store.ROOT.iterdir())
    await _ingest_ways(derived_before, ONEWAY)

    async def fail():
        raise RuntimeError("段の後で落ちた")

    _observe_after("ways", monkeypatch, fail)

    with pytest.raises(RuntimeError, match="段の後で落ちた"):
        await derive_cli.run(postgis_database_url(), None)

    assert await derived_before.fetchval(
        "SELECT direction FROM way_materials WHERE osm_way_id = 100") == "both"
    assert await _revision(derived_before) == 1
    assert sorted(road_network_store.ROOT.iterdir()) == network_before
    assert await _schemas(derived_before) == schemas_at_start


async def _nodes_with_signal(conn: asyncpg.Connection) -> set[int]:
    return {r["osm_node_id"] for r in await conn.fetch(
        "SELECT osm_node_id FROM node_materials WHERE has_traffic_signals")}


async def test_the_signal_radius_set_on_the_admin_screen_decides_which_nodes_get_the_signal(derived_before):
    """管理画面で変えた「信号とみなす半径」で、作り直した交差点の信号の判定が変わる。

    信号はノード2だけ。隣のノード1・3は約140m、ノード4は約180m離れている。
    """
    await ingest_records("osm_node", [
        point_record(n, *_point(n), {"highway": "traffic_signals"} if n == 2 else None) for n in range(1, 5)],
        conn=derived_before)

    assert await derive_cli.run(postgis_database_url(), None) == 0
    assert await _nodes_with_signal(derived_before) == {2}

    await derived_before.execute(
        "INSERT INTO tuning_overrides (param_id, value) VALUES ('signal.match_radius_m', 150.0)")
    try:
        assert await derive_cli.run(postgis_database_url(), "nodes") == 0
    finally:
        await derived_before.execute("DELETE FROM tuning_overrides WHERE param_id = 'signal.match_radius_m'")
    assert await _nodes_with_signal(derived_before) == {1, 2, 3}


async def test_the_accident_density_is_divided_by_the_years_of_the_import_that_was_counted(
        derived_before, road_graph_engine, monkeypatch):
    """事故密度の分母（収録年数）は、今の表を作った事故の取込の年から読む。取り込み直しても、作り直しが
    入れ替わるまでは前の取込の年のまま（数も前のまま）で、入れ替えた後は新しい取込の年になり、その世代の
    道路網も新しい年数で割っている。"""

    async def accident_years() -> list[int]:
        async with AsyncSession(road_graph_engine) as session:
            return await RoadGraphRepository(session).get_accident_years()

    def density_on_way_100() -> float:
        network = road_network_store.current()
        column = network.numeric_ids.index(ACCIDENT_COUNT_PER_KM_YEAR)
        return float(network.numeric_values[network.edge_way_id == 100, column].max())

    # 道100の途中のノード2の上で、自転車の関わった事故が1件。
    accident = point_record("on-way-100", *_point(2), {
        "当事者種別（当事者A）": PARTY_TYPE_CODES[PartyType.BICYCLE], "当事者種別（当事者B）": "59", "死者数": "000"})
    await ingest_records("accident", [accident], conn=derived_before, rows=HonhyoRows(years=[2024]))
    assert await derive_cli.run(postgis_database_url(), None) == 0
    one_year = density_on_way_100()

    await ingest_records("accident", [accident], conn=derived_before, rows=HonhyoRows(years=[2023, 2024]))
    seen_while_rebuilding: list[list[int]] = []

    async def observe():
        seen_while_rebuilding.append(await accident_years())

    _observe_after("counts", monkeypatch, observe)
    years_before_rebuild = await accident_years()

    assert await derive_cli.run(postgis_database_url(), None) == 0

    # 前提: 1年で割った密度が出ている。
    assert one_year > 0
    assert (years_before_rebuild, seen_while_rebuilding) == ([2024], [[2024]])
    assert await accident_years() == [2023, 2024]
    assert density_on_way_100() == pytest.approx(one_year / 2)


async def test_a_rebuild_records_the_latest_succeeded_import_of_every_source(derived_before):
    """入れ替えた後、全ソースの成功した最新の取込が、今の表を作った取込として記録されている。後から失敗した取込は記録しない。"""
    way_run = await _ingest_ways(derived_before)
    node_run = await ingest_records("osm_node", [point_record(n, *_point(n)) for n in range(1, 5)],
                                    conn=derived_before)
    address_run = await _ingest_addresses(derived_before)

    def breaks():
        yield point_record(1, *_point(1))
        raise OSError("配信元が途中で切れた")

    with pytest.raises(OSError):
        await ingest_records("osm_node", breaks(), conn=derived_before)

    assert await derive_cli.run(postgis_database_url(), None) == 0

    assert await derived_data_meta.read_source_runs(derived_before) == {
        "osm_way": way_run, "osm_node": node_run, "abr": address_run}


async def _record_a_column_added_after_the_rebuild(conn: asyncpg.Connection) -> None:
    """最後の作り直しの後に、道1本の表へ列を1本足した（作ったときの列の記録に、今の宣言の列が1本無い）。"""
    columns = await derived_data_meta.read_columns(conn)
    await derived_data_meta.replace_columns(conn, {**columns, "way_materials": columns["way_materials"] - {"divided"}})


@pytest.mark.parametrize("change", [_ingest_ways, _record_a_column_added_after_the_rebuild],
                         ids=["生データを取り直した", "派生の表の列を足した"])
async def test_rebuilding_from_a_stage_stops_after_a_change_until_rebuilt_from_the_first_stage(derived_before, change):
    """生データを取り直した・派生の表の列を足した後は、途中の段からは流さず何も変えない。最初から流した後は、途中の段から流せる。"""
    await change(derived_before)

    with pytest.raises(RuntimeError, match="--from を外して最初から流す"):
        await derive_cli.run(postgis_database_url(), "ways")
    assert await _revision(derived_before) == 1

    assert await derive_cli.run(postgis_database_url(), None) == 0
    assert await derive_cli.run(postgis_database_url(), "ways") == 0
    assert await _revision(derived_before) == 3


async def test_an_import_is_refused_while_a_rebuild_runs(derived_before, monkeypatch):
    """作り直しの段の間に取込を始めると、取込は何も書かずに止まる。"""
    runs_before = await derived_before.fetchval("SELECT count(*) FROM source_runs")

    async def import_meanwhile():
        with pytest.raises(RuntimeError, match="派生の作り直しが走っている"):
            await ingest_records("accident", [], conn=derived_before)

    _observe_after("topology", monkeypatch, import_meanwhile)

    assert await derive_cli.run(postgis_database_url(), None) == 0
    assert await derived_before.fetchval("SELECT count(*) FROM source_runs") == runs_before
