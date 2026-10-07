"""生データ（`source_features`・`source_runs`）を、取込の入口（`app/batch/ingest.py: ingest_source`）から入れる足場。

生データを読む側（派生の段・取り込んだ範囲・タイル）のテストは、本番と同じく取込を通った生データから始める
（docs/conventions/testing.md パターン8）。表へ直接書くと、取込では作れない行（成功なのに終わった時刻の無いrun等）が
でき、取込の側が変わってもテストは気づかない。

差し替えるのはアダプタ（外部の形を開いて1件ずつ返す部分）だけで、テストが渡した1件ずつをそのまま返す。
runの記録・パーティション・入れ替えは本物を通す。外部の形の読み方は各アダプタのテスト（例: `test_gsi_dem_tile.py`）が見る。

入れ直すと、そのソースの行は丸ごと入れ替わり、新しいrunになる（本番の取り直しと同じ）。行を変えたいテストは、
変えた後の全行を渡して入れ直す。失敗したrunは、途中で例外を投げる`records`を渡して作る。
"""

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import replace
from typing import Any

import asyncpg
import shapely
from shapely.geometry import LineString, Point

from app.batch.ingest import ADAPTERS, RegisteredAdapter, SourceRecord, ingest_source
from app.batch.source_adapters.raster_wkb import tile_bbox_wkb
from app.batch.source_adapters.osm_pbf import way_payload
from app.batch.source_profile import NoFields, SourceProfile, SourceSpec, Target, load_source_profile
from app.infrastructure.source_models import WAY_KIND_TAG
from tests.conftest import raw_connection

#: テストが渡した行を返すアダプタの名前。取込の間だけ`ADAPTERS`に置く。
_ADAPTER = "given_records"


def way_record(way_id: int, points: Sequence[tuple[float, float]], node_ids: Sequence[int],
               tags: dict[str, str] | None = None) -> SourceRecord:
    """道（`osm_way`）の1件。`points`は頂点の (経度, 緯度) の列で、`node_ids`と1対1に対応する。

    道は種別を持たないと表に入らない。`tags`が種別を書かなければ、階級の付かない種別（自転車道）を補う。
    """
    return SourceRecord(natural_key=str(way_id), geom_wkb=shapely.to_wkb(LineString(points)),
                        attrs={WAY_KIND_TAG: "cycleway", **(tags or {})}, payload=way_payload(node_ids))


def point_record(key: int | str, lon: float, lat: float,
                 attrs: dict[str, Any] | None = None) -> SourceRecord:
    """点のソース（`osm_node`・`accident`）の1件。"""
    return SourceRecord(natural_key=str(key), geom_wkb=shapely.to_wkb(Point(lon, lat)),
                        attrs=attrs or {})


def tile_record(key: str, zoom: int, x: int, y: int, rast: bytes,
                attrs: dict[str, Any]) -> SourceRecord:
    """面のソース（例: `lulc`）のタイル1枚。"""
    return SourceRecord(natural_key=key, geom_wkb=tile_bbox_wkb(zoom, x, y), attrs=attrs, rast=rast)


def _profile(source: str, bbox: tuple[float, float, float, float] | None, rows: Any) -> SourceProfile:
    """本物の宣言のまま、`source`のアダプタだけを差し替えたもの。runにはそのソースの本物の絞り込みが残る。"""
    profile = load_source_profile(None)
    spec: SourceSpec = replace(profile.source(source), adapter=_ADAPTER)
    if rows is not None:
        spec = replace(spec, rows=rows)
    return replace(
        profile,
        target=profile.target if bbox is None else Target(bbox=bbox),
        sources=tuple(spec if s.name == source else s for s in profile.sources),
    )


async def ingest_records(source: str, records: Iterable[SourceRecord], *,
                         conn: asyncpg.Connection | None = None,
                         bbox: tuple[float, float, float, float] | None = None,
                         rows: Any = None) -> int:
    """`records`を`source`の生データとして取り込み、`run_id`を返す。

    `conn`はトランザクションの外の接続（取込の入口の求め）。渡さなければ自分で開いて閉じる——SQLAlchemyの
    セッションで書くテストは、取込を先に済ませてからセッションで読み書きする。`bbox`は取込の範囲の宣言
    （(min_lat, min_lon, max_lat, max_lon)）で、省けば本物の宣言の範囲。`rows`はそのソースの絞り込みの宣言
    （例: 事故の年`HonhyoRows`）で、省けば本物の宣言。
    """
    async def read(spec: SourceSpec, profile: SourceProfile,
                   origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
        for record in records:
            yield record

    if conn is None:
        async with raw_connection() as connection:
            return await ingest_records(source, records, conn=connection, bbox=bbox, rows=rows)
    ADAPTERS[_ADAPTER] = RegisteredAdapter(read=read, rows=NoFields, grid=NoFields)
    try:
        return await ingest_source(conn, _profile(source, bbox, rows), source)
    finally:
        del ADAPTERS[_ADAPTER]
