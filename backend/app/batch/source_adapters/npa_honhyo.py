"""警察庁 交通事故統計オープンデータ（本票CSV）のアダプタ。

**外部の形を読んで1件ずつ返すことだけ**を行う。ステージング・差し替え・run記録は
`ingest.py`の共通経路が持つ。

**配信元は叩かない。** 取りに行くのは`scripts/fetch_accident_csv.py`の仕事で、ここは
手元にあるものを読む。

列は捨てずに全部`attrs`へ入れる。何が後で要るかは取込の時点では決められない——
2022年に列構成が58列から68列へ変わっており、そのとき何を拾うべきだったかは
後から見ないと分からない。

絞りはbboxで行う。行政区画で絞るには警察庁独自の採番とJIS X 0401の対応表が要るが、
母集団の指定としてはbboxで足りる。
"""

import csv
import logging
from collections.abc import AsyncIterator
from typing import Any
from pathlib import Path

import shapely
from shapely.geometry import Point

from app.batch.ingest import SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec
from app.domain.accident import latitude_from_raw, longitude_from_raw

logger = logging.getLogger("ridecompass.ingest.npa_honhyo")

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "accidents"

#: 本票CSVの文字コード。
ENCODING = "cp932"

#: 緯度・経度の列名（度分秒をつないだ数字列で入っている）。
_LAT_HEADER = "地点　緯度（北緯）"
_LON_HEADER = "地点　経度（東経）"


def _honhyo_path(year: int) -> Path:
    path = DATA_DIR / f"honhyo_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"本票CSVがありません: {path}（scripts/fetch_accident_csv.py が写す）")
    return path


@register_adapter("npa_honhyo")
async def read_npa_honhyo(spec: SourceSpec, profile: SourceProfile,
                          origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    target = profile.target
    years = spec.rows.get("years") or []
    origin["files"] = []
    min_lat, min_lon, max_lat, max_lon = target.bbox
    skipped = 0
    for year in years:
        path = _honhyo_path(int(year))
        origin["files"].append({"year": int(year), **file_origin(path)})
        with open(path, encoding=ENCODING, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lat = latitude_from_raw(row.get(_LAT_HEADER, ""))
                lon = longitude_from_raw(row.get(_LON_HEADER, ""))
                if lat is None or lon is None:
                    skipped += 1
                    continue
                if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                    continue
                natural_key = "-".join((
                    str(year),
                    row.get("都道府県コード", ""),
                    row.get("警察署等コード", ""),
                    row.get("本票番号", ""),
                ))
                yield SourceRecord(
                    natural_key=natural_key,
                    geom_wkb=shapely.to_wkb(Point(lon, lat)),
                    attrs={k: v for k, v in row.items() if k},
                )
    if skipped:
        logger.warning("座標が読めずスキップした行: %d件", skipped)
