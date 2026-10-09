"""派生の作り直し（`batch/derive_cli.py`）が、入力（読むソースの取込・前の段・較正値・書く表の列・段のコード）が前回と
同じ段を流さないことと、段の宣言（`STAGES`）が段の読むもの・書くものを漏らしていないこと。

流した段は段の関数が呼ばれたかで見る。飛ばした段のある作り直しの表の値は、同じ入力で全部の段を流した作り直しと比べる。
どの生データにも行があり、どの段も値を書く小さな世界（道2本・信号・事故・標高と土地被覆のタイル・住所・小地域の境界・
地点・寺社の建物）から始める。

ここで見ないもの: 入れ替えまで読み手に前の表を見せること・取込の記録・較正値の読み方 → `test_derive_cli.py`。
段の値の出し方 → 段ごとのテスト（`test_derive_*.py`）。
"""

import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from app.batch import code_fingerprint, derive_cli
from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.batch.source_adapters.npa_honhyo import HonhyoRows
from app.batch.source_adapters.raster_wkb import tile_raster_wkb
from app.domain.accident import PartyType
from app.domain.landcover import PERCENT_CLASSES
from app.domain.region import BoundingBox
from app.infrastructure.derived_data_freshness import declared_columns, derived_tables
from app.infrastructure.source_models import PARTY_TYPE_CODES, Source
from tests.conftest import empty_ingested_tables, postgis_database_url, raw_connection
from tests.source_ingest import (
    abr_city_record,
    abr_prefecture_record,
    abr_town_record,
    dem_tile_records,
    estat_small_area_record,
    ingest_records,
    point_record,
    tile_record,
    way_record,
    zigzag_point,
)

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: 道とノードは土地被覆のタイル（ズーム14の1枚。約2km四方）の中ほどに置く。区間の帯（中心線から100m）もこの1枚に収まる。
BASE_LON, BASE_LAT = 139.688, 35.683
STEP = 0.0005
LULC_ZOOM, LULC_X, LULC_Y, LULC_SIZE = 14, 14549, 6451, 256
WAYS = ((100, [1, 2, 3]), (200, [3, 4]))
SHINJUKU = ("東京都", "新宿区", "")
SIGNAL_RADIUS = "signal.match_radius_m"
STAGE_NAMES = [stage.name for stage in derive_cli.STAGES]


def _point(node_id: int) -> tuple[float, float]:
    return zigzag_point(node_id, (BASE_LON, BASE_LAT), STEP)


async def _ingest_ways(conn: asyncpg.Connection) -> None:
    await ingest_records("osm_way", [way_record(way_id, [_point(n) for n in nodes], nodes, {"highway": "residential"})
                                     for way_id, nodes in WAYS], conn=conn)


async def _ingest_nodes(conn: asyncpg.Connection) -> None:
    await ingest_records("osm_node", [point_record(n, *_point(n), {"highway": "traffic_signals"} if n == 2 else None)
                                      for n in range(1, 5)], conn=conn)


async def _ingest_accidents(conn: asyncpg.Connection) -> None:
    await ingest_records("accident", [point_record("on-way-100", *_point(2), {
        "当事者種別（当事者A）": PARTY_TYPE_CODES[PartyType.BICYCLE], "当事者種別（当事者B）": "59", "死者数": "000"})],
        conn=conn, rows=HonhyoRows(years=[2024]))


async def _ingest_elevations(conn: asyncpg.Connection) -> None:
    area = BoundingBox(min_latitude=BASE_LAT - 0.001, min_longitude=BASE_LON,
                       max_latitude=BASE_LAT + 0.002, max_longitude=BASE_LON + 0.003)
    await ingest_records("dem", dem_tile_records(PRODUCT_PRIORITY[0], 15, area,
                                                 lambda lon, lat: 10 + (lon - BASE_LON) * 1000), conn=conn)


async def _ingest_landcover(conn: asyncpg.Connection) -> None:
    await ingest_records("lulc", [tile_record(
        "tile", LULC_ZOOM, LULC_X, LULC_Y,
        tile_raster_wkb(bytes([PERCENT_CLASSES[0][1]]) * LULC_SIZE ** 2, zoom=LULC_ZOOM, x=LULC_X, y=LULC_Y,
                        width=LULC_SIZE, height=LULC_SIZE, dtype="uint8", nodata=0),
        {"z": LULC_ZOOM, "x": LULC_X, "y": LULC_Y, "width": LULC_SIZE})], conn=conn)


async def _ingest_addresses(conn: asyncpg.Connection) -> None:
    await ingest_records("abr", [
        abr_prefecture_record("130001", "東京都", *_point(1)),
        abr_city_record("131041", "東京都", "新宿区", *_point(1)),
        abr_town_record("131041", "0024000", "1", SHINJUKU, *_point(2), oaza="西新宿"),
    ], conn=conn)


async def _ingest_places(conn: asyncpg.Connection) -> None:
    await ingest_records("overture_place", [point_record("cafe", *_point(2), {
        "names": {"primary": "喫茶店"}, "confidence": 0.75, "brand": {"names": {"primary": None}},
        "taxonomy": {"hierarchy": ["food_and_drink", "cafe"]}})], conn=conn)


@pytest_asyncio.fixture(loop_scope="module")
async def world(road_graph_engine, road_network_root):
    """どの生データにも行がある世界を取り込み、全部の段を流して作り直した後の接続。道路網の置き場は一時ディレクトリ。

    `road_graph_engine`に依存するのはスキーマを作らせるため。
    """
    async with raw_connection() as conn:
        await empty_ingested_tables(conn)
        try:
            await _ingest_ways(conn)
            await _ingest_nodes(conn)
            await _ingest_accidents(conn)
            await _ingest_elevations(conn)
            await _ingest_landcover(conn)
            await _ingest_addresses(conn)
            west, south = _point(1)
            await ingest_records("estat_small_area", [estat_small_area_record("13104002400", "西新宿", [
                (west, south - 0.001), (west, south + 0.002), (west + 0.003, south + 0.002),
                (west + 0.003, south - 0.001), (west, south - 0.001)])], conn=conn)
            await _ingest_places(conn)
            await ingest_records("bunka_heritage", [point_record("bunka-1", *_point(3), {"bunka-14-s": "宗教法人神田神社"})],
                                 conn=conn)
            assert await derive_cli.run(postgis_database_url()) == 0
            yield conn
        finally:
            await conn.execute(f"DROP SCHEMA IF EXISTS {derive_cli._WORK_SCHEMA} CASCADE")
            await conn.execute("DELETE FROM tuning_overrides WHERE param_id = $1", SIGNAL_RADIUS)
            await empty_ingested_tables(conn)
            await conn.execute("TRUNCATE derived_data_meta")


@pytest.fixture
def ran(world, monkeypatch) -> list[str]:
    """`world`を作った後に、関数が呼ばれた段の名前（呼ばれた順）。段そのものは本物を通す。"""
    names: list[str] = []
    for stage in derive_cli.STAGES:
        async def derive(conn, *, _real=stage.module.derive, _name=stage.name, **tuning):
            names.append(_name)
            return await _real(conn, **tuning)

        monkeypatch.setattr(stage.module, "derive", derive)
    return names


async def _values(conn: asyncpg.Connection) -> dict[str, str]:
    """派生の表ごとの、全部の行と値のハッシュ。"""
    return {table.name: await conn.fetchval(
        f"SELECT md5(coalesce(string_agg(r::text, '|' ORDER BY r::text), '')) FROM {table.name} r")  # noqa: S608 宣言のみ
        for table in derived_tables()}


async def _revision(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT revision FROM derived_data_meta")


async def test_the_world_fills_every_derived_table(world):
    """前提: 比べる表はどれも行を持ち、飛ばした段の値が空の表どうしの比べにならない。"""
    assert {table.name: await world.fetchval(f"SELECT count(*) > 0 FROM {table.name}")  # noqa: S608 宣言のみ
            for table in derived_tables()} == {table.name: True for table in derived_tables()}


async def test_rebuilding_with_the_same_inputs_runs_no_stage_and_changes_nothing(world, ran, caplog):
    """入力が前回と同じなら、どの段の関数も呼ばれず、表・世代は前のまま。そのことをログに出す。"""
    values, revision = await _values(world), await _revision(world)
    caplog.set_level(logging.INFO, logger="ridecompass.derive_cli")

    assert await derive_cli.run(postgis_database_url()) == 0

    assert ran == []
    assert await _values(world) == values
    assert await _revision(world) == revision
    assert "どの段も入力が前回と同じ" in caplog.text


async def _set_signal_radius(conn: asyncpg.Connection, monkeypatch, tmp_path: Path) -> None:
    await conn.execute("INSERT INTO tuning_overrides (param_id, value) VALUES ($1, 150.0)", SIGNAL_RADIUS)


def _add_column(table: str):
    """派生の表`table`の宣言に列を足した（表の列は足したことにしない。段の指紋だけが列の宣言を読む）。"""
    async def change(conn: asyncpg.Connection, monkeypatch, tmp_path: Path) -> None:
        columns = declared_columns()
        monkeypatch.setattr(derive_cli, "declared_columns",
                            lambda: {**columns, table: columns[table] | {"added_column"}})
    return change


def _edit_code(module: str, edit: Callable[[str], str]):
    """`app`の写しの`module`（`app`からのパス）を`edit`で書き換え、段のコードの指紋をその写しから読む。"""
    async def change(conn: asyncpg.Connection, monkeypatch, tmp_path: Path) -> None:
        shutil.copytree(code_fingerprint.ROOT / "app", tmp_path / "app",
                        ignore=shutil.ignore_patterns("__pycache__"))
        path = tmp_path / "app" / module
        path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
        monkeypatch.setattr(code_fingerprint, "ROOT", tmp_path)
    return change


def _reingest(ingest: Callable[[asyncpg.Connection], Awaitable[None]]):
    async def change(conn: asyncpg.Connection, monkeypatch, tmp_path: Path) -> None:
        await ingest(conn)
    return change


@dataclass(frozen=True)
class Change:
    name: str
    apply: Callable[[asyncpg.Connection, pytest.MonkeyPatch, Path], Awaitable[None]]
    #: 流れるはずの段（段の順）。
    runs: tuple[str, ...]


ROAD_STAGES = ("topology", "nodes", "counts", "elevation", "landcover", "ways")
CHANGES = [
    Change("事故を取り直した", _reingest(_ingest_accidents), ("counts",)),
    Change("ノードを取り直した", _reingest(_ingest_nodes), ("nodes", "counts")),
    Change("標高を取り直した", _reingest(_ingest_elevations), ("elevation",)),
    Change("土地被覆を取り直した", _reingest(_ingest_landcover), ("landcover",)),
    # 住所の段は道路の取込の範囲を読む。
    Change("道を取り直した", _reingest(_ingest_ways), tuple(STAGE_NAMES)),
    Change("住所を取り直した", _reingest(_ingest_addresses), ("addresses", "stop_places")),
    Change("地点を取り直した", _reingest(_ingest_places), ("stop_places",)),
    Change("信号とみなす半径を変えた", _set_signal_radius, ("nodes", "counts")),
    Change("道1本の表に列を足した", _add_column("way_materials"), ROAD_STAGES),
    Change("立ち寄り先の表に列を足した", _add_column("stop_places"), ("stop_places",)),
    # 標高のタイルの置き場は標高の段だけが読み込む。
    Change("標高の段が読み込むモジュールを変えた", _edit_code("batch/dem_tile_store.py", lambda text: text + "\n_EDITED = 1\n"),
           ("elevation",)),
]


@pytest.mark.parametrize("change", CHANGES, ids=[change.name for change in CHANGES])
async def test_only_the_stages_whose_inputs_changed_run_and_the_values_match_a_full_rebuild(
        world, ran, caplog, monkeypatch, tmp_path, change):
    """入力を変えると、それを読む段とその後ろの段だけが流れ、ほかの段は飛ばしたとログに出る。できた表の値は、同じ入力で
    全部の段を流した作り直しと同じ。"""
    caplog.set_level(logging.INFO, logger="ridecompass.derive_cli")
    await change.apply(world, monkeypatch, tmp_path)

    assert await derive_cli.run(postgis_database_url()) == 0
    skipped = {record.args[0] for record in caplog.records if record.msg == "段 %s を飛ばした（入力が前回と同じ）"}
    values = await _values(world)

    assert (ran, skipped) == (list(change.runs), set(STAGE_NAMES) - set(change.runs) if change.runs else set())

    await world.execute("DELETE FROM derived_stages")
    ran.clear()
    assert await derive_cli.run(postgis_database_url()) == 0
    assert ran == STAGE_NAMES
    assert await _values(world) == values


@dataclass
class Touched:
    """段1回が触ったもの。"""

    #: 読んだソース（パーティションを読んだもの）。
    sources: set[str]
    #: 読んだ派生の表（書いた表も、書くときに読む）。
    read: set[str]
    #: 書いた派生の表。
    written: set[str]
    #: 行を入れた・消した派生の表。
    rows: set[str]


#: この接続が表を触った数のうち、まだ書き出していないもの（公式の文書「The Cumulative Statistics System」の
#: `pg_stat_xact_user_tables`。トランザクションの途中から読める）。書き出しは待機に入るときなので、前のトランザクションの分も
#: 残っている——段の前と後を同じトランザクションの中で読んで差を取る。
_TOUCHED_SQL = """
SELECT schemaname, relname, coalesce(seq_scan, 0) + coalesce(idx_scan, 0) AS scans,
       n_tup_ins + n_tup_del AS rows, n_tup_ins + n_tup_upd + n_tup_del AS written
FROM pg_stat_xact_user_tables WHERE schemaname IN ('public', $1)
"""


async def _counts(conn: asyncpg.Connection) -> dict[tuple[str, str], dict[str, int]]:
    return {(row["schemaname"], row["relname"]): {kind: row[kind] for kind in ("scans", "rows", "written")}
            for row in await conn.fetch(_TOUCHED_SQL, derive_cli._WORK_SCHEMA)}


def _ancestors(name: str) -> set[str]:
    stages = {stage.name: stage for stage in derive_cli.STAGES}
    found: set[str] = set()
    pending = list(stages[name].after)
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(stages[current].after)
    return found


async def test_each_stage_declares_what_it_reads_and_writes(world, monkeypatch):
    """全部の段を流し、段ごとに読んだソース・派生の表と書いた表を数えて、宣言と比べる。

    - 読んだソースは宣言のソース（住所の段の道路は、パーティションを読まず取込の記録から範囲だけを読むので数に出ない）。
    - 書いた表は宣言の表。
    - 読むだけの表を書く前の段と、書く表の行を入れる・消す前の段は、どれも前の段（たどった先も）にある。
    """
    derived = {table.name for table in derived_tables()}
    touched: dict[str, Touched] = {}
    for stage in derive_cli.STAGES:
        async def derive(conn, *, _real=stage.module.derive, _name=stage.name, **tuning):
            # 数の段が自分のトランザクションに分離レベルを付け、asyncpg は入れ子に外側と同じレベルを求めるので、外側をそれに揃える。
            async with conn.transaction(isolation="repeatable_read"):
                before = await _counts(conn)
                await _real(conn, **tuning)
                after = await _counts(conn)
            grew = {table: {kind: n - before.get(table, {}).get(kind, 0) for kind, n in counts.items()}
                    for table, counts in after.items()}
            work = {name: counts for (schema, name), counts in grew.items()
                    if schema == derive_cli._WORK_SCHEMA and name in derived}
            touched[_name] = Touched(
                sources={name.removeprefix("source_features_") for (schema, name), counts in grew.items()
                         if schema == "public" and name.startswith("source_features_") and counts["scans"]},
                read={name for name, counts in work.items() if counts["scans"]},
                written={name for name, counts in work.items() if counts["written"]},
                rows={name for name, counts in work.items() if counts["rows"]})

        monkeypatch.setattr(stage.module, "derive", derive)
    await world.execute("DELETE FROM derived_stages")

    assert await derive_cli.run(postgis_database_url()) == 0

    assert {name: touched[name].sources for name in STAGE_NAMES} == {
        stage.name: set(stage.sources) - ({Source.OSM_WAY} if stage.name == "addresses" else set())
        for stage in derive_cli.STAGES}
    assert {name: touched[name].written for name in STAGE_NAMES} == {
        stage.name: set(stage.tables) for stage in derive_cli.STAGES}
    missing: dict[str, set[str]] = {}
    for index, stage in enumerate(derive_cli.STAGES):
        mine = touched[stage.name]
        for prior in derive_cli.STAGES[:index]:
            if prior.name not in _ancestors(stage.name) and (
                    (mine.read - mine.written) & touched[prior.name].written or mine.written & touched[prior.name].rows):
                missing.setdefault(stage.name, set()).add(prior.name)
    assert missing == {}
