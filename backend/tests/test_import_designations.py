import json
from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio
from shapely.geometry import LineString

from app.batch._common import asyncpg_dsn
from app.batch.import_designations import (
    _INSERT_SQL,
    _KIND_SPECS,
    _parse_n10_gml,
    _parse_n12_geojson,
    _write_designations,
    _zip_url,
)
from app.domain.designation import DESIGNATION_IMPORT_KINDS
from tests.conftest import TEST_DATABASE_URL


class TestKindSpecs:
    def test_covers_every_import_kind(self):
        # 改善計画T75: kind集合の正準はDESIGNATION_IMPORT_KINDS（domain/designation.py）。
        # _KIND_SPECSはここに列挙されたkind全てをカバーしている必要がある。
        assert set(_KIND_SPECS.keys()) == set(DESIGNATION_IMPORT_KINDS)

    def test_zip_url_formats_prefecture_into_kind_specific_template(self):
        assert _zip_url("emergency_transport", "13") == (
            "https://nlftp.mlit.go.jp/ksj/gml/data/N10/N10-15/N10-15_13_GML.zip"
        )
        assert _zip_url("critical_logistics", "13") == (
            "https://nlftp.mlit.go.jp/ksj/gml/data/N12/N12-21/N12-21_13_GML.zip"
        )

    def test_unknown_kind_raises_key_error(self):
        # 未知kindは暗黙のフォールバックへ倒さずKeyErrorで即死させる（改善計画T75）。
        with pytest.raises(KeyError):
            _zip_url("national_cycle_route", "13")


class TestParseN12Geojson:
    def test_reads_linestring(self):
        data = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[139.0, 35.0], [139.1, 35.1]]},
                    "properties": {"N12_004": "テスト路線"},
                }
            ]
        }
        features = _parse_n12_geojson(json.dumps(data).encode())
        assert features == [("テスト路線", [(139.0, 35.0), (139.1, 35.1)])]

    def test_ignores_altitude_in_3element_coordinates(self):
        # RFC 7946は[lon, lat, alt]の3要素座標を許容する。改善計画T72: 従来は
        # `for lon, lat in coordinates`がValueErrorになりrun全体が異常終了していた。
        data = {
            "features": [
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[139.0, 35.0, 12.3], [139.1, 35.1, 15.0]],
                    },
                    "properties": {},
                }
            ]
        }
        features = _parse_n12_geojson(json.dumps(data).encode())
        assert features == [(None, [(139.0, 35.0), (139.1, 35.1)])]

    def test_expands_multilinestring_into_multiple_features(self):
        # 改善計画T72: MultiLineStringは以前typeが一致せず無警告でスキップされ、
        # 路線が黙って欠落していた。
        data = {
            "features": [
                {
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [
                            [[139.0, 35.0], [139.1, 35.1]],
                            [[140.0, 36.0], [140.1, 36.1]],
                        ],
                    },
                    "properties": {"N12_004": "分岐路線"},
                }
            ]
        }
        features = _parse_n12_geojson(json.dumps(data).encode())
        assert features == [
            ("分岐路線", [(139.0, 35.0), (139.1, 35.1)]),
            ("分岐路線", [(140.0, 36.0), (140.1, 36.1)]),
        ]

    def test_skips_unsupported_geometry_type_without_raising(self):
        data = {
            "features": [
                {"geometry": {"type": "Point", "coordinates": [139.0, 35.0]}, "properties": {}},
            ]
        }
        assert _parse_n12_geojson(json.dumps(data).encode()) == []


class TestParseN10Gml:
    _GML_HEADER = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Dataset xmlns:gml="http://www.opengis.net/gml/3.2" '
        'xmlns:ksj="http://nlftp.mlit.go.jp/ksj/schemas/ksj-app" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
    )

    def test_reads_single_segment_curve(self):
        xml = (
            self._GML_HEADER
            + '<gml:Curve gml:id="c1"><gml:segments><gml:LineStringSegment>'
            + "<gml:posList>35.0 139.0 35.1 139.1</gml:posList>"
            + "</gml:LineStringSegment></gml:segments></gml:Curve>"
            + '<ksj:UrgentTransportationRoad><ksj:loc xlink:href="#c1"/>'
            + "<ksj:rdn>テスト路線</ksj:rdn></ksj:UrgentTransportationRoad>"
            + "</Dataset>"
        ).encode()

        features = _parse_n10_gml(xml)

        assert features == [("テスト路線", [(139.0, 35.0), (139.1, 35.1)])]

    def test_concatenates_multiple_line_string_segments(self):
        # 改善計画T72: JPGISは1つのgml:Curveが複数のgml:LineStringSegment(=複数posList)を
        # 持つことを許容する。従来は`.find`で最初の1つしか読まず、2番目以降が無警告で
        # 切り捨てられていた。
        xml = (
            self._GML_HEADER
            + '<gml:Curve gml:id="c1"><gml:segments>'
            + "<gml:LineStringSegment><gml:posList>35.0 139.0 35.1 139.1</gml:posList></gml:LineStringSegment>"
            + "<gml:LineStringSegment><gml:posList>35.1 139.1 35.2 139.2</gml:posList></gml:LineStringSegment>"
            + "</gml:segments></gml:Curve>"
            + '<ksj:UrgentTransportationRoad><ksj:loc xlink:href="#c1"/>'
            + "</ksj:UrgentTransportationRoad>"
            + "</Dataset>"
        ).encode()

        features = _parse_n10_gml(xml)

        assert features == [(None, [(139.0, 35.0), (139.1, 35.1), (139.1, 35.1), (139.2, 35.2)])]


@pytest_asyncio.fixture
async def designation_conn():
    try:
        conn = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")
    try:
        await conn.execute("DELETE FROM route_designations")
        yield conn
    finally:
        await conn.execute("DELETE FROM route_designations")
        await conn.close()


async def _seed_route_designation(conn: asyncpg.Connection, kind: str, pref: str, name: str = "既存路線") -> None:
    await conn.execute(
        _INSERT_SQL,
        kind, name, pref, "ksj_n10", LineString([(139.0, 35.0), (139.1, 35.1)]).wkb,
        datetime.now(timezone.utc),
    )


class TestWriteDesignations:
    async def test_skips_delete_when_features_are_empty(self, designation_conn):
        # 改善計画T71 問題2: パーサが0件を返した場合もDELETEだけ実行され、既存データが
        # 静かに消えていた。0件時はDELETEごとスキップし既存行を保持する。
        await _seed_route_designation(designation_conn, "emergency_transport", "13")

        count = await _write_designations(
            designation_conn, "emergency_transport", "13", "ksj_n10", [], datetime.now(timezone.utc)
        )

        assert count == 0
        remaining = await designation_conn.fetchval(
            "SELECT count(*) FROM route_designations WHERE kind = $1 AND pref_code = $2",
            "emergency_transport", "13",
        )
        assert remaining == 1

    async def test_replaces_existing_rows_with_new_features(self, designation_conn):
        await _seed_route_designation(designation_conn, "emergency_transport", "13", name="旧路線")

        count = await _write_designations(
            designation_conn,
            "emergency_transport",
            "13",
            "ksj_n10",
            [("新路線", [(139.2, 35.2), (139.3, 35.3)])],
            datetime.now(timezone.utc),
        )

        assert count == 1
        rows = await designation_conn.fetch(
            "SELECT name FROM route_designations WHERE kind = $1 AND pref_code = $2",
            "emergency_transport", "13",
        )
        assert [r["name"] for r in rows] == ["新路線"]

    async def test_rolls_back_delete_when_insert_fails_midway(self, designation_conn, monkeypatch):
        # 改善計画T71 問題1: DELETEとINSERTがトランザクション外だったため、INSERT側の
        # 失敗で「旧データDELETE済み・新データ一部のみ」の中途半端な状態が確定していた。
        await _seed_route_designation(designation_conn, "emergency_transport", "13", name="旧路線")

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        # asyncpg.Connectionはインスタンス属性の上書きを許さない（__slots__）ため、
        # クラス側のメソッドをmonkeypatchする。
        monkeypatch.setattr(asyncpg.Connection, "executemany", _boom)

        with pytest.raises(RuntimeError):
            await _write_designations(
                designation_conn,
                "emergency_transport",
                "13",
                "ksj_n10",
                [("新路線", [(139.2, 35.2), (139.3, 35.3)])],
                datetime.now(timezone.utc),
            )

        rows = await designation_conn.fetch(
            "SELECT name FROM route_designations WHERE kind = $1 AND pref_code = $2",
            "emergency_transport", "13",
        )
        assert [r["name"] for r in rows] == ["旧路線"]
