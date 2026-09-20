"""国土数値情報（KSJ）の指定路線のアダプタ。

配布は都道府県別のZIPで、キーはJIS X 0401。プロファイルも同じ採番で書くため、
ここに採番の対応表を持たない。

ZIPの中身の読み方（N10はJPGIS/GML、N12は素のGeoJSON）は`import_designations.py`が
持っているものを使う——同じ外部仕様を2度読み解かない。
"""

import logging
from collections.abc import AsyncIterator

import httpx
import shapely
from shapely.geometry import LineString

from app.batch.import_designations import _download_zip, extract_features
from app.batch.ingest import SourceRecord, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec

logger = logging.getLogger("ridecompass.ingest.ksj_designation")


@register_adapter("ksj_designation")
async def read_ksj_designations(spec: SourceSpec, profile: SourceProfile) -> AsyncIterator[SourceRecord]:
    target = profile.target
    kinds = spec.rows.get("kinds") or []
    prefectures = target.prefectures
    if prefectures is None:
        raise ValueError("指定路線は都道府県別に配布されるため、target.prefectures が要ります")

    async with httpx.AsyncClient() as client:
        for kind in kinds:
            for pref in prefectures:
                zip_path = await _download_zip(client, kind, pref)
                if zip_path is None:
                    logger.warning("取得できませんでした: kind=%s pref=%s", kind, pref)
                    continue
                for index, (name, coords) in enumerate(extract_features(zip_path, kind, pref)):
                    if len(coords) < 2:
                        continue
                    yield SourceRecord(
                        natural_key=f"{kind}/{pref}/{index}",
                        geom_wkb=shapely.to_wkb(LineString(coords)),
                        attrs={"kind": kind, "pref_code": pref, "name": name},
                    )
