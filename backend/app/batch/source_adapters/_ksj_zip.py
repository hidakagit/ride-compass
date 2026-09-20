"""KSJ（国土数値情報）の都道府県別ZIPの読み取り。

**N10とN12でファイル形式が異なる**（N10はGeoJSON非対応）:

- N10: ZIP内の`N10-15_{pref}.xml`がJPGIS/GML（`gml:Curve`＋`ksj:UrgentTransportationRoad`、
  xlinkで参照）。標準ライブラリの`xml.etree.ElementTree`でパースする。
- N12: ZIP内の`N12-21_{pref}.geojson`が素のGeoJSON。

配布のキーはJIS X 0401で、取込プロファイルも同じ採番で書く。
"""

import json
import logging
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx

from app.batch._common import download_to_path

logger = logging.getLogger("ridecompass.ingest.ksj_zip")

# backend/app/batch/source_adapters/ から見て backend/data/designations/
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "designations"

N10_URL_TEMPLATE = "https://nlftp.mlit.go.jp/ksj/gml/data/N10/N10-15/N10-15_{pref}_GML.zip"
N12_URL_TEMPLATE = "https://nlftp.mlit.go.jp/ksj/gml/data/N12/N12-21/N12-21_{pref}_GML.zip"

_GML_NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "ksj": "http://nlftp.mlit.go.jp/ksj/schemas/ksj-app",
    "xlink": "http://www.w3.org/1999/xlink",
}



async def _download_zip(client: httpx.AsyncClient, kind: str, pref: str) -> Path | None:
    """都道府県別ZIPを直接取得しDATA_DIRへ保存する（骨格はapp/batch/_common.py:
    download_to_pathへ共通化されている）。

    保存名はURL側のファイル名（`N10-15_08_GML.zip`のようにKSJの配信版数を含む）をその
    まま使う。`download_to_path`は同名ファイルが既にあればHTTPアクセスごとスキップする
    ため、保存名が版数を含まないと新しい版のURLへ更新して再実行しても旧版のZIPを
    パースし続け、成功として記録される。"""
    url = _zip_url(kind, pref)
    dest = DATA_DIR / _zip_file_name(url)
    return await download_to_path(
        client, url, dest, logger=logger, label="指定路線データ", context=f"kind={kind} pref={pref}"
    )


def _parse_n10_gml(xml_bytes: bytes) -> list[tuple[str | None, list[tuple[float, float]]]]:
    """N10のJPGIS/GMLから (路線名, [(lon, lat), ...]) のリストを返す。

    2パス構成（import_pbf.pyのnode辞書→way解決と同型）: 全gml:Curveをid→座標リストの
    辞書にした後、ksj:UrgentTransportationRoadをxlink:hrefで解決する。
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_bytes)
    curves: dict[str, list[tuple[float, float]]] = {}
    for curve in root.iter(f"{{{_GML_NS['gml']}}}Curve"):
        curve_id = curve.get(f"{{{_GML_NS['gml']}}}id")
        # JPGISでは1つのgml:Curveが複数のgml:LineStringSegment（＝複数posList）を持ちうる。
        # findで最初の1つだけ読むと2番目以降が無警告で切り捨てられ、件数は合うまま
        # バッファ交差率だけが縮んで後半区間が指定路線と判定されなくなる。
        # 全posListをdocument順に連結する（連続するセグメント列という前提）。
        pos_list_els = curve.findall(".//gml:posList", _GML_NS)
        if curve_id is None or not pos_list_els:
            continue
        if len(pos_list_els) > 1:
            logger.warning(
                "gml:Curveが複数posListを持っています（連結して扱います） curve_id=%s segments=%d",
                curve_id, len(pos_list_els),
            )
        values: list[float] = []
        for pos_list_el in pos_list_els:
            text = (pos_list_el.text or "").strip()
            if text:
                values.extend(float(v) for v in text.split())
        if not values:
            continue
        # posListは「lat lon lat lon...」の順（GML実データで確認済み）。
        # shapely/GeoJSON慣行の(lon, lat)へ入れ替える。
        curves[curve_id] = [(values[i + 1], values[i]) for i in range(0, len(values) - 1, 2)]

    features: list[tuple[str | None, list[tuple[float, float]]]] = []
    for feature in root.iter(f"{{{_GML_NS['ksj']}}}UrgentTransportationRoad"):
        loc = feature.find("ksj:loc", _GML_NS)
        if loc is None:
            continue
        curve_id = (loc.get(f"{{{_GML_NS['xlink']}}}href") or "").lstrip("#")
        coords = curves.get(curve_id)
        if not coords or len(coords) < 2:
            continue
        name_el = feature.find("ksj:rdn", _GML_NS)
        features.append((name_el.text if name_el is not None else None, coords))
    return features


def _linestrings_from_geometry(geometry: dict) -> list[list]:
    """LineString/MultiLineString双方から素の座標配列のリストを返す
    （MultiLineStringのfeatureも扱わないと路線が黙って欠落するため）。
    それ以外のtype（Point等、KSJでは想定外）は空リスト。
    """
    geometry_type = geometry.get("type")
    if geometry_type == "LineString":
        return [geometry.get("coordinates", [])]
    if geometry_type == "MultiLineString":
        return list(geometry.get("coordinates", []))
    return []


def _parse_n12_geojson(json_bytes: bytes) -> list[tuple[str | None, list[tuple[float, float]]]]:
    """N12の素のGeoJSONから (路線名, [(lon, lat), ...]) のリストを返す。"""
    data = json.loads(json_bytes)
    features: list[tuple[str | None, list[tuple[float, float]]]] = []
    skipped_types: dict[str, int] = {}
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        lines = _linestrings_from_geometry(geometry)
        if not lines:
            geometry_type = geometry.get("type") or "unknown"
            skipped_types[geometry_type] = skipped_types.get(geometry_type, 0) + 1
            continue
        name = (feature.get("properties") or {}).get("N12_004")
        for raw_coords in lines:
            # RFC 7946は[lon, lat, alt]の3要素座標を許容するため、先頭2要素のみ取得する
            # （3要素のままunpackするとValueErrorになるため）。
            coords = [(float(c[0]), float(c[1])) for c in raw_coords]
            if len(coords) < 2:
                continue
            features.append((name, coords))
    if skipped_types:
        logger.warning("N12ジオメトリのうち非対応typeをスキップしました types=%s", skipped_types)
    return features


@dataclass(frozen=True)
class _DesignationKindSpec:
    """kind→(取得URL・DB上のsource値・ZIP内メンバー名・パーサ)の対応。

    未知kindは`_KIND_SPECS[kind]`のKeyErrorで即死させる（暗黙のフォールバックを許さない）。
    """

    url_template: str
    source: str
    member_template: str  # {pref}でformatするZIP内メンバー名
    parser: Callable[[bytes], list[tuple[str | None, list[tuple[float, float]]]]]


_KIND_SPECS: dict[str, _DesignationKindSpec] = {
    "emergency_transport": _DesignationKindSpec(
        url_template=N10_URL_TEMPLATE, source="ksj_n10", member_template="N10-15_{pref}.xml", parser=_parse_n10_gml
    ),
    "critical_logistics": _DesignationKindSpec(
        url_template=N12_URL_TEMPLATE,
        source="ksj_n12",
        member_template="N12-21_{pref}.geojson",
        parser=_parse_n12_geojson,
    ),
}


def _zip_url(kind: str, pref: str) -> str:
    return _KIND_SPECS[kind].url_template.format(pref=pref)


def _zip_file_name(url: str) -> str:
    """取得URLのパス末尾（`N10-15_08_GML.zip`）をローカル保存名として使う
    （`_download_zip`のdocstring参照）。"""
    return PurePosixPath(urlsplit(url).path).name


def extract_features(zip_path: Path, kind: str, pref: str) -> list[tuple[str | None, list[tuple[float, float]]]]:
    """ZIP内の該当ファイル（N10=xml, N12=geojson）を展開しパースする（メモリ上、
    抽出ファイルをディスクへ書かない）。"""
    spec = _KIND_SPECS[kind]
    member_name = spec.member_template.format(pref=pref)

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member_name) as f:
            return spec.parser(f.read())
