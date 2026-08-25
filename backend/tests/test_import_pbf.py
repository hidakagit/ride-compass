"""PBF取込バッチ（app/batch/import_pbf.py）の純粋ロジックの検証。

DB・PBFファイルを要する結合部分（TestRunImportOrchestration）は改善計画T331で追加。
実際のPBFファイル・pyosmiumのストリーム読み取りは使わず、app.batch.pbf_sourceの
read_header/stream_ways（唯一のosmium依存箇所）をモックへ差し替えて、run_import本体
（producer/consumerパイプライン・プロファイルマッチング・COPY→MERGE・タイルマーク・
GiST遅延構築・run記録・失敗時のstatus更新）をDB結合で検証する。
scripts/verify_phase1_e2e.py（実DB・実PBF E2E）はこのテストと独立に維持する。
"""

from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from shapely import wkb as shapely_wkb

from app.batch import import_pbf, pbf_source
from app.batch._common import asyncpg_dsn
from app.batch.import_pbf import (
    _status_count,
    build_poi_record,
    build_way_record,
    parse_bbox,
    poi_in_bbox,
    run_import,
    way_in_bbox,
)
from app.domain.graph import WaySpec
from app.domain.osm_adapter import POISpec
from app.domain.region import BoundingBox
from tests.conftest import TEST_DATABASE_URL

# xdist_group="postgis": pbf_import_connは同じridecompass_test DBのosm_raw_ways等を
# 無条件DELETEで初期化する。他のpostgis系テストと別workerで並走すると互いのDELETEで
# 相手のseed行が消えるflaky失敗を起こすため固定する（docs/testing.md参照）。
pytestmark = pytest.mark.xdist_group(name="postgis")

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "app" / "batch" / "import_profile.yaml"


class TestParseBbox:
    def test_valid(self):
        bbox = parse_bbox("35.60,139.65,35.75,139.85")
        assert bbox == BoundingBox(
            min_latitude=35.60, min_longitude=139.65, max_latitude=35.75, max_longitude=139.85
        )

    @pytest.mark.parametrize("text", ["35.6,139.65,35.75", "35.75,139.65,35.60,139.85", "a,b,c,d"])
    def test_invalid_raises(self, text):
        with pytest.raises(ValueError):
            parse_bbox(text)


class TestWayInBbox:
    BBOX = BoundingBox(min_latitude=35.0, min_longitude=139.0, max_latitude=36.0, max_longitude=140.0)

    def test_no_bbox_accepts_everything(self):
        assert way_in_bbox({1: (0.0, 0.0)}, None)

    def test_any_node_inside_is_enough(self):
        coords = {1: (34.0, 138.0), 2: (35.5, 139.5)}  # 1つ目は外、2つ目が中
        assert way_in_bbox(coords, self.BBOX)

    def test_all_nodes_outside_is_rejected(self):
        assert not way_in_bbox({1: (34.0, 138.0), 2: (34.5, 138.5)}, self.BBOX)


class TestBuildWayRecord:
    def _spec(self, node_ids, **overrides) -> WaySpec:
        fields = dict(osm_way_id=100, node_ids=node_ids, highway="residential", surface="asphalt", direction="both")
        fields.update(overrides)
        return WaySpec(**fields)

    def test_record_fields_and_wkb_geometry(self):
        coords = {1: (35.0, 139.0), 2: (35.001, 139.001)}
        record = build_way_record(self._spec([1, 2]), coords)
        assert record[:4] == (100, [1, 2], "residential", "asphalt")
        assert record[5] == "both"
        line = shapely_wkb.loads(record[6])
        # WKBは(lon, lat)順で格納される（PostGIS/Shapelyの座標順）
        assert list(line.coords) == [(139.0, 35.0), (139.001, 35.001)]

    def test_geometry_skips_nodes_without_coords(self):
        coords = {1: (35.0, 139.0), 3: (35.002, 139.002)}  # ノード2は位置不明
        record = build_way_record(self._spec([1, 2, 3]), coords)
        assert record[1] == [1, 2, 3]  # node_ids配列は完全なまま保持する
        line = shapely_wkb.loads(record[6])
        assert list(line.coords) == [(139.0, 35.0), (139.002, 35.002)]

    def test_fewer_than_two_known_coords_yields_null_geom(self):
        record = build_way_record(self._spec([1, 2]), {1: (35.0, 139.0)})
        assert record[6] is None

    def test_tags_are_json_serialized(self):
        record = build_way_record(self._spec([1, 2], tags={"smoothness": "good"}), {})
        assert record[4] == '{"smoothness": "good"}'

    def test_empty_tags_serialize_to_empty_json_object(self):
        record = build_way_record(self._spec([1, 2]), {})
        assert record[4] == "{}"


class TestPoiInBbox:
    BBOX = BoundingBox(min_latitude=35.0, min_longitude=139.0, max_latitude=36.0, max_longitude=140.0)

    def _spec(self, latitude, longitude) -> POISpec:
        return POISpec(osm_node_id=1, kind="traffic_signals", latitude=latitude, longitude=longitude)

    def test_no_bbox_accepts_everything(self):
        assert poi_in_bbox(self._spec(0.0, 0.0), None)

    def test_inside_bbox_is_accepted(self):
        assert poi_in_bbox(self._spec(35.5, 139.5), self.BBOX)

    def test_outside_bbox_is_rejected(self):
        assert not poi_in_bbox(self._spec(34.0, 138.0), self.BBOX)


class TestBuildPoiRecord:
    def test_record_fields(self):
        spec = POISpec(osm_node_id=200, kind="crossing", tags={"highway": "crossing"}, latitude=35.0, longitude=139.0)
        record = build_poi_record(spec)
        assert record == (200, "crossing", '{"highway": "crossing"}', 139.0, 35.0)

    def test_empty_tags_serialize_to_empty_json_object(self):
        spec = POISpec(osm_node_id=200, kind="stop", latitude=35.0, longitude=139.0)
        record = build_poi_record(spec)
        assert record[2] == "{}"


def test_status_count_parses_asyncpg_command_status():
    assert _status_count("INSERT 0 123") == 123
    assert _status_count("TRUNCATE TABLE") == 0


@pytest_asyncio.fixture
async def pbf_import_conn():
    try:
        conn = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")

    async def _cleanup():
        await conn.execute("DELETE FROM osm_raw_pois")
        await conn.execute("DELETE FROM osm_raw_ways")
        await conn.execute("DELETE FROM osm_raw_nodes")
        await conn.execute("DELETE FROM osm_import_runs")
        await conn.execute("DELETE FROM road_graph_tiles")

    try:
        await _cleanup()
        yield conn
    finally:
        await _cleanup()
        await conn.close()


# fake_stream_waysが流すway/node（1組は取込プロファイルに一致、もう1組は非一致）。
# 実装のosm_adapter.py: osm_way_to_way_spec / osm_node_to_poi_specが受け取るのと
# 同じ形（{"id", "tags", "nodes"} / {"id", "tags", "lat", "lon"}）。
_MATCHING_WAY = ({"id": 1, "tags": {"highway": "cycleway"}, "nodes": [10, 11]}, {10: (35.50, 139.50), 11: (35.51, 139.51)})
_NON_MATCHING_WAY = (
    {"id": 2, "tags": {"highway": "motorway"}, "nodes": [12, 13]},  # import_profile.yamlのroadsルール対象外
    {12: (35.50, 139.50), 13: (35.51, 139.51)},
)
_MATCHING_NODE = {"id": 20, "tags": {"highway": "traffic_signals"}, "lat": 35.505, "lon": 139.505}
_NON_MATCHING_NODE = {"id": 21, "tags": {"amenity": "restaurant"}, "lat": 35.506, "lon": 139.506}  # プロファイル対象外

_TEST_BBOX_TEXT = "35.0,139.0,36.0,140.0"


def _make_fake_stream_ways(*, raise_error: bool = False):
    """pbf_source.stream_waysの代替（pyosmium非依存）。

    実際のosmium.SimpleHandler.way/node（app/batch/pbf_source.py: _WayHandler）と同じく、
    tag_filter/node_tag_filter（matching_ruleベース）を通った要素だけをsink/node_sinkへ渡す
    ことで、run_import〜プロファイルマッチングの結線を実プロファイルYAMLで検証できるようにする。
    """

    def fake_stream_ways(pbf_path, tag_filter, sink, node_tag_filter=None, node_sink=None) -> None:
        if raise_error:
            raise RuntimeError("pbf読み取りに失敗しました（テスト用）")
        for raw_way, coords in (_MATCHING_WAY, _NON_MATCHING_WAY):
            if tag_filter(raw_way["tags"]):
                sink(raw_way, coords)
        if node_sink is not None:
            for raw_node in (_MATCHING_NODE, _NON_MATCHING_NODE):
                if node_tag_filter(raw_node["tags"]):
                    node_sink(raw_node)

    return fake_stream_ways


def _fake_read_header(pbf_path):
    return "2024-01-01T00:00:00Z", None


class TestRunImportOrchestration:
    """run_import本体（producer/consumerパイプライン・プロファイルマッチング・
    COPY→MERGE・タイルマーク・GiST遅延構築・run記録）の結合検証（改善計画T331）。

    run_importのオーケストレーション本体（メイン処理フロー）はこれまでCI未検証で
    手動E2Eスクリプトでしか確認されていなかった。pyosmium（PBF読み取り）はこのモジュール
    唯一の依存箇所であるapp.batch.pbf_source.read_header/stream_waysをモックへ差し替える
    ことで回避し、実PBFファイル無しでrun_import本体を結合検証する。
    """

    def _patch_pbf_source(self, monkeypatch, *, raise_error: bool = False):
        monkeypatch.setattr(pbf_source, "read_header", _fake_read_header)
        monkeypatch.setattr(pbf_source, "stream_ways", _make_fake_stream_ways(raise_error=raise_error))

    async def test_writes_ways_nodes_pois_and_marks_run_succeeded(self, pbf_import_conn, tmp_path, monkeypatch):
        self._patch_pbf_source(monkeypatch)
        pbf_path = tmp_path / "fake.osm.pbf"
        pbf_path.write_bytes(b"")  # is_file()チェックのみ通ればよい（中身はpbf_source側でモック済み）

        result = await run_import(
            str(pbf_path), str(DEFAULT_PROFILE_PATH), _TEST_BBOX_TEXT, TEST_DATABASE_URL, dry_run=False
        )

        assert result == 0
        way_rows = await pbf_import_conn.fetch("SELECT osm_way_id, highway FROM osm_raw_ways")
        # highway=motorwayのwayはimport_profile.yamlのroadsルール対象外のため取り込まれない。
        assert [dict(r) for r in way_rows] == [{"osm_way_id": 1, "highway": "cycleway"}]

        node_ids = {r["osm_node_id"] for r in await pbf_import_conn.fetch("SELECT osm_node_id FROM osm_raw_nodes")}
        # 取り込まれたwayが参照するノードのみ（非対象wayのノード12,13は入らない）。
        assert node_ids == {10, 11}

        poi_rows = await pbf_import_conn.fetch("SELECT osm_node_id, kind FROM osm_raw_pois")
        # amenity=restaurantは静的道路属性P1のいずれの分類にも該当せず対象外。
        assert [dict(r) for r in poi_rows] == [{"osm_node_id": 20, "kind": "traffic_signals"}]

        run_row = await pbf_import_conn.fetchrow(
            "SELECT status, way_count, node_count, pbf_timestamp FROM osm_import_runs"
        )
        assert run_row["status"] == "succeeded"
        assert run_row["way_count"] == 1
        assert run_row["node_count"] == 2

        tile_count = await pbf_import_conn.fetchval("SELECT count(*) FROM road_graph_tiles")
        assert tile_count > 0  # --bbox指定時はタイルを取得済みマークする

        # 改善計画T28: 初回（空テーブル）取込は完了後にGiSTを再構築する。取込後に
        # インデックスが存在することを確認する（存在しないまま放置される回帰を検知）。
        index_exists = await pbf_import_conn.fetchval(
            "SELECT to_regclass('idx_osm_raw_ways_geom') IS NOT NULL"
        )
        assert index_exists is True

    async def test_dry_run_does_not_touch_db(self, tmp_path, monkeypatch):
        # dry_run時はDB接続自体を行わない（DB fixture不要＝DB未起動でも実行できるテスト）。
        self._patch_pbf_source(monkeypatch)
        pbf_path = tmp_path / "fake.osm.pbf"
        pbf_path.write_bytes(b"")

        result = await run_import(
            str(pbf_path), str(DEFAULT_PROFILE_PATH), _TEST_BBOX_TEXT, TEST_DATABASE_URL, dry_run=True
        )

        assert result == 0

    async def test_returns_error_when_pbf_file_missing(self, tmp_path):
        # PBFファイル自体が存在しない場合、pbf_source（pyosmium）のimportにすら
        # 到達せずrun_importが1を返すことを確認する（モック不要・DB fixture不要）。
        result = await run_import(
            str(tmp_path / "missing.osm.pbf"), str(DEFAULT_PROFILE_PATH), None, TEST_DATABASE_URL, dry_run=False
        )

        assert result == 1

    async def test_marks_run_failed_and_reraises_when_pbf_read_fails(self, pbf_import_conn, tmp_path, monkeypatch):
        # producerスレッド（pbf_source.stream_ways）が例外を送出した場合、run記録が
        # failedへ更新されたうえで例外が呼び出し元へ再送出されることを確認する
        # （import_pbf.py: run_importの`if producer.error is not None: raise producer.error`）。
        self._patch_pbf_source(monkeypatch, raise_error=True)
        pbf_path = tmp_path / "fake.osm.pbf"
        pbf_path.write_bytes(b"")

        with pytest.raises(RuntimeError, match="pbf読み取りに失敗しました"):
            await run_import(
                str(pbf_path), str(DEFAULT_PROFILE_PATH), _TEST_BBOX_TEXT, TEST_DATABASE_URL, dry_run=False
            )

        run_row = await pbf_import_conn.fetchrow("SELECT status FROM osm_import_runs")
        assert run_row["status"] == "failed"
        assert await pbf_import_conn.fetchval("SELECT count(*) FROM osm_raw_ways") == 0

    async def test_second_run_on_non_empty_table_skips_deferred_index_rebuild(
        self, pbf_import_conn, tmp_path, monkeypatch
    ):
        # 改善計画T28: 2回目以降（テーブルが空でない）はGiST再構築を遅延させない
        # （DROP INDEXしない）分岐を通る。初回・再取込の両方が正常完了することを確認する。
        self._patch_pbf_source(monkeypatch)
        pbf_path = tmp_path / "fake.osm.pbf"
        pbf_path.write_bytes(b"")

        first = await run_import(
            str(pbf_path), str(DEFAULT_PROFILE_PATH), _TEST_BBOX_TEXT, TEST_DATABASE_URL, dry_run=False
        )
        second = await run_import(
            str(pbf_path), str(DEFAULT_PROFILE_PATH), _TEST_BBOX_TEXT, TEST_DATABASE_URL, dry_run=False
        )

        assert first == 0
        assert second == 0
        # ON CONFLICT DO UPDATEのため重複せず1件のまま。
        assert await pbf_import_conn.fetchval("SELECT count(*) FROM osm_raw_ways") == 1
        assert await pbf_import_conn.fetchval("SELECT count(*) FROM osm_import_runs") == 2


