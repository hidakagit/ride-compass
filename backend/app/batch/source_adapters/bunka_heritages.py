"""国の指定・登録の文化財の建造物（文化遺産オンラインの項目をジャパンサーチの API で取ったもの）のアダプタ。

**外部の形を読んで1件ずつ返すことだけ**を行う。寺社かの判断と、同じ寺社の建物を1つにまとめるのは派生の段
（`batch/derive_stop_places.py`）で、ここは取り込む母集団の外の行を落とすだけである。

**配信元は叩かない。** 取りに行くのは`scripts/fetch_bunka_heritages.py`の仕事で、ここは手元にあるもの
（全国の建造物の項目を1行1件の JSON で並べたファイル）を読む。

落とすのは次の行:
- 位置が無い
- 取込の範囲（`target.bbox`）の外
- 指定の別（`bunka-11-s`）が宣言（`rows.designations`）に無い——建造物の項目には、史跡・美術品・世界遺産の構成資産等の
  建物でない指定も混ざる

残した行の項目は全部`attrs`へ入れる。
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import Point

from app.batch.ingest import AdapterInputs, SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "bunka"

#: 指定の別の項目。
DESIGNATION_FIELD = "bunka-11-s"


@dataclass(frozen=True)
class BunkaHeritageRows:
    """`bunka_heritages`の`rows`。"""

    #: 取った日（例: `2026-10-08`）。配信元は版を持たず今の一覧だけを返すので、取った日ごとに置き場を分ける。
    snapshot: str
    #: 取り込む指定の別（文化遺産オンラインの表記のまま）。
    designations: list[str]


def heritages_path(snapshot: str) -> Path:
    """取り出した項目の置き場。取得（`scripts/fetch_bunka_heritages.py`）と取込で同じ導き方を使う。"""
    return DATA_DIR / f"architecture_{snapshot}.jsonl"


def _existing_heritages_path(rows: BunkaHeritageRows) -> Path:
    path = heritages_path(rows.snapshot)
    if not path.exists():
        raise FileNotFoundError(f"文化財の建造物の一覧がありません: {path}（scripts/fetch_bunka_heritages.py が写す）")
    return path


def bunka_heritages_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    return AdapterInputs(files=(_existing_heritages_path(spec.rows),))


@register_adapter("bunka_heritages", rows=BunkaHeritageRows, inputs=bunka_heritages_inputs)
async def read_bunka_heritages(spec: SourceSpec, profile: SourceProfile,
                               origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    rows: BunkaHeritageRows = spec.rows
    path = _existing_heritages_path(rows)
    origin.update({"snapshot": rows.snapshot, **file_origin(path)})
    designations = set(rows.designations)
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            item = json.loads(line)
            coordinates = item["common"].get("coordinates")
            if coordinates is None or item.get(DESIGNATION_FIELD) not in designations:
                continue
            lat, lon = coordinates["lat"], coordinates["lon"]
            if not profile.target.contains(lat, lon):
                continue
            yield SourceRecord(natural_key=item["id"], geom_wkb=shapely.to_wkb(Point(lon, lat)), attrs=item)
