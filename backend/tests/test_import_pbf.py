"""PBF取込バッチ（app/batch/import_pbf.py）の純粋ロジックの検証。

DB・PBFファイルを要する結合部分はscripts/verify_phase1_e2e.py（実DB E2E）で検証する。
"""

import pytest
from shapely import wkb as shapely_wkb

from app.batch.import_pbf import _status_count, build_way_record, parse_bbox, way_in_bbox
from app.domain.graph import WaySpec
from app.domain.region import BoundingBox


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


def test_status_count_parses_asyncpg_command_status():
    assert _status_count("INSERT 0 123") == 123
    assert _status_count("TRUNCATE TABLE") == 0


def test_asyncpg_dsn_normalizes_driver_and_ssl_param():
    from app.batch.import_pbf import _asyncpg_dsn

    assert (
        _asyncpg_dsn("postgresql+asyncpg://u:p@db.example.supabase.co:5432/postgres?ssl=require")
        == "postgresql://u:p@db.example.supabase.co:5432/postgres?sslmode=require"
    )
    # ローカル（ssl指定なし）はドライバ指定の除去のみ
    assert (
        _asyncpg_dsn("postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass")
        == "postgresql://ridecompass:ridecompass@localhost:5432/ridecompass"
    )
