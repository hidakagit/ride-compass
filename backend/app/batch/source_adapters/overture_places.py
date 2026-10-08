"""Overture Maps の地点（places の GeoParquet）のアダプタ。

**外部の形を読んで1件ずつ返すことだけ**を行う。群へ入れる・近くの同じ店をまとめるのは派生の段
（`batch/derive_stop_places.py`）で、ここは取り込む母集団の外の地点を落とすだけである。

**配信元は叩かない。** 取りに行くのは`scripts/fetch_overture_places.py`の仕事で、ここは手元にあるものを読む。

落とすのは次の地点:
- 取込の範囲（`target.bbox`）の外
- 確からしさ（`confidence`）が宣言（`rows.min_confidence`）より低い。閉じた地点は0になる
- 分類の道筋に、どの群の語（`domain/stop_place.py: OVERTURE_GROUPED_WORDS`）も無い——群の外の地点が配布の大半で、
  取り込んでも読む者がいない
- 名前が無い（地図にも検索にも出せない）

残した地点の列は、位置（`geometry`・`bbox`）を除いて全部`attrs`へ入れる。
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from app.batch.ingest import SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec
from app.domain.stop_place import OVERTURE_GROUPED_WORDS

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "overture"

#: 1回に読み出す行の数。DuckDBから溜めずに流すための区切り。
_FETCH_ROWS = 10_000

_SELECT_SQL = """
-- 位置の列は`geom`へ入れるので属性から除く（マージパッチの null はそのキーを消す。RFC 7386）。
SELECT p.id, ST_AsWKB(p.geometry), json_merge_patch(to_json(p), '{"geometry": null, "bbox": null}')
FROM read_parquet(?) p
WHERE p.bbox.xmin BETWEEN ? AND ? AND p.bbox.ymin BETWEEN ? AND ?
  AND p.confidence >= ?
  AND list_has_any(p.taxonomy.hierarchy, ?::VARCHAR[])
  AND p.names.primary IS NOT NULL
"""


@dataclass(frozen=True)
class OverturePlaceRows:
    """`overture_places`の`rows`。"""

    #: 配布の版（例: `2026-09-23.1`）。版ごとに配布の置き場が分かれる。
    release: str
    #: これより確からしさの低い地点は取り込まない。
    min_confidence: float


def places_path(release: str) -> Path:
    """取り出した地点の置き場。取得（`scripts/fetch_overture_places.py`）と取込で同じ導き方を使う。"""
    return DATA_DIR / f"places_{release}.parquet"


@register_adapter("overture_places", rows=OverturePlaceRows)
async def read_overture_places(spec: SourceSpec, profile: SourceProfile,
                               origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    rows: OverturePlaceRows = spec.rows
    path = places_path(rows.release)
    if not path.exists():
        raise FileNotFoundError(f"Overture の地点がありません: {path}（scripts/fetch_overture_places.py が写す）")
    origin.update({"release": rows.release, **file_origin(path)})
    min_lat, min_lon, max_lat, max_lon = profile.target.bbox
    # 点の`bbox`の最小は点そのもの（公式の文書「DuckDB」の Overture の読み方）。
    with duckdb.connect() as conn:
        conn.execute(_SELECT_SQL, [str(path), min_lon, max_lon, min_lat, max_lat, rows.min_confidence,
                                   sorted(OVERTURE_GROUPED_WORDS)])
        while batch := conn.fetchmany(_FETCH_ROWS):
            for place_id, wkb, attrs in batch:
                yield SourceRecord(natural_key=place_id, geom_wkb=bytes(wkb), attrs=json.loads(attrs))
