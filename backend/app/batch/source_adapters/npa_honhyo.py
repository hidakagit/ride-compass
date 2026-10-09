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
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

import shapely
from shapely.geometry import Point

from app.batch.ingest import AdapterInputs, SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec

logger = logging.getLogger("ridecompass.ingest.npa_honhyo")

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "accidents"

#: 本票CSVの文字コード。
ENCODING = "cp932"

#: 緯度・経度の列名（度分秒をつないだ数字列で入っている）。
_LAT_HEADER = "地点　緯度（北緯）"
_LON_HEADER = "地点　経度（東経）"


def _dms_to_decimal(raw: str) -> float | None:
    """本票の緯度・経度列（度分秒を1つの数値へ連結した表記。右5桁=秒×1000、
    次の2桁=分、残り=度）を10進の度へ変換する。欠損（空・非数値）や
    分/秒が60以上になる不正値はNone（根拠のない推測はしない）。

    全て0の列は0度として通す。日本の範囲外として落とすのは`latitude_from_raw`／
    `longitude_from_raw`の側で、ここは表記の解釈だけを負う。"""
    value = raw.strip()
    if not value.isdigit() or len(value) < 8:
        return None
    seconds = int(value[-5:]) / 1000.0
    minutes = int(value[-7:-5])
    degrees = int(value[:-7])
    if minutes >= 60 or seconds >= 60:
        return None
    return degrees + minutes / 60.0 + seconds / 3600.0


# 日本の緯度・経度のおおよその範囲（南鳥島・沖ノ鳥島等の離島を含む広めの値）。
# 度分秒からの変換結果が壊れていないかを見るためだけのもので、対象地域の絞り込みではない。
_JAPAN_LATITUDE_RANGE = (20.0, 46.0)
_JAPAN_LONGITUDE_RANGE = (122.0, 154.0)


def latitude_from_raw(raw: str) -> float | None:
    value = _dms_to_decimal(raw)
    if value is None or not (_JAPAN_LATITUDE_RANGE[0] <= value <= _JAPAN_LATITUDE_RANGE[1]):
        return None
    return value


def longitude_from_raw(raw: str) -> float | None:
    value = _dms_to_decimal(raw)
    if value is None or not (_JAPAN_LONGITUDE_RANGE[0] <= value <= _JAPAN_LONGITUDE_RANGE[1]):
        return None
    return value


def honhyo_path(year: int) -> Path:
    """本票CSVの置き場。取得（`scripts/fetch_accident_csv.py`）と取込で同じ導き方を使う。"""
    return DATA_DIR / f"honhyo_{year}.csv"


def _existing_honhyo_path(year: int) -> Path:
    path = honhyo_path(year)
    if not path.exists():
        raise FileNotFoundError(
            f"本票CSVがありません: {path}（scripts/fetch_accident_csv.py が写す）")
    return path


@dataclass(frozen=True)
class HonhyoRows:
    """`npa_honhyo`の`rows`。"""

    #: 取り込む年。1年が本票CSV1ファイル。
    years: list[int] = field(default_factory=list)


def npa_honhyo_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    return AdapterInputs(files=tuple(_existing_honhyo_path(int(year)) for year in spec.rows.years))


@register_adapter("npa_honhyo", rows=HonhyoRows, inputs=npa_honhyo_inputs)
async def read_npa_honhyo(spec: SourceSpec, profile: SourceProfile,
                          origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    target = profile.target
    years = spec.rows.years
    origin["files"] = []
    min_lat, min_lon, max_lat, max_lon = target.bbox
    skipped = 0
    for year in years:
        path = _existing_honhyo_path(int(year))
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
