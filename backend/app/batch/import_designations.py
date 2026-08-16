"""国土数値情報（KSJ）N10（緊急輸送道路）・N12（重要物流道路）→PostGIS取込バッチ
（docs/external-data-sources-review-2026-08-16.md §4.3、docs/improvement-plan.md T51）。

都道府県別ZIP（`N10-15_{pref}_GML.zip`/`N12-21_{pref}_GML.zip`）を、都道府県コードだけで
組み立てられる公開URLから直接取得し（`backend/data/designations/`へ一時保存、git管理外）、
関東7都県分を`route_designations`へ投入する。import_accidents.pyと同様、ダウンロード
＋バッチのみでユーザー作業は不要（KSJ利用規約はPDL1.0相当、登録不要・非商用利用可、
出典明記のみ必須。2026-08-16確認）。

**N10とN12でファイル形式が異なる**（2026-08-16実データ確認、レビュー当初の想定と異なり
N10はGeoJSON非対応）:
- N10: ZIP内の`N10-15_{pref}.xml`がJPGIS/GML（`gml:Curve`＋`ksj:UrgentTransportationRoad`、
  xlinkで参照）。標準ライブラリ`xml.etree.ElementTree`でパースする（新規依存ライブラリ
  不要。GDAL系（fiona/geopandas）もシェープファイル用のpyshpも導入しない）。
- N12: ZIP内の`N12-21_{pref}.geojson`が素のGeoJSON。標準ライブラリ`json`でパースする。

**冪等性**: 事故データ（`accident_id`という自然キーがある）と異なり、KSJの行には
安定した外部IDが無いため、ステージング→MERGEではなく「(kind, pref_code)単位で
DELETE→INSERT」で冪等にする（同じ都道府県・種別を再取込みしても重複が蓄積しない）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.import_designations --database-url ...

--dry-runで件数集計のみ（DB書き込みなし）。関東7都県固定（対象を絞る意味が無いため
引数化しない、import_accidents.pyの--yearsのような可変軸が無い）。
"""

import argparse
import asyncio
import json
import logging
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
from shapely.geometry import LineString
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.infrastructure import designation_models  # noqa: F401  Base.metadataへモデル登録するためのimport
from app.infrastructure.migrate import apply_pending_migrations
from app.infrastructure.road_graph_repository import create_tables

logger = logging.getLogger("app.batch.import_designations")

# KSJの都道府県コード（JIS X 0401準拠の標準採番。domain/accident.pyのKANTO_PREFECTURE_CODES
# はNPA独自採番で別物のため流用しない）。
KANTO_PREFECTURE_CODES_KSJ: dict[str, str] = {
    "08": "茨城", "09": "栃木", "10": "群馬", "11": "埼玉", "12": "千葉", "13": "東京", "14": "神奈川",
}

N10_URL_TEMPLATE = "https://nlftp.mlit.go.jp/ksj/gml/data/N10/N10-15/N10-15_{pref}_GML.zip"
N12_URL_TEMPLATE = "https://nlftp.mlit.go.jp/ksj/gml/data/N12/N12-21/N12-21_{pref}_GML.zip"

# backend/app/batch/import_designations.py から見て backend/data/designations/
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "designations"

_GML_NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "ksj": "http://nlftp.mlit.go.jp/ksj/schemas/ksj-app",
    "xlink": "http://www.w3.org/1999/xlink",
}

_DELETE_SQL = "DELETE FROM route_designations WHERE kind = $1 AND pref_code = $2"
_INSERT_SQL = """
INSERT INTO route_designations (kind, name, pref_code, attrs, source, geom, updated_at)
VALUES ($1, $2, $3, '{}'::jsonb, $4, ST_SetSRID(ST_GeomFromWKB($5), 4326), $6)
"""


def _zip_url(kind: str, pref: str) -> str:
    return (N10_URL_TEMPLATE if kind == "emergency_transport" else N12_URL_TEMPLATE).format(pref=pref)


def _source_for_kind(kind: str) -> str:
    return "ksj_n10" if kind == "emergency_transport" else "ksj_n12"


async def _download_zip(client: httpx.AsyncClient, kind: str, pref: str) -> Path | None:
    """都道府県別ZIPを直接取得しDATA_DIRへ保存する。404等の取得失敗はWARNINGで常時出力し
    その都道府県をスキップする（docs/logging.mdのエラー常時WARNING方針）。既にダウンロード
    済み（同名ファイルが存在）ならHTTPアクセスを省略する。
    """
    dest = DATA_DIR / f"{kind}_{pref}.zip"
    if dest.exists():
        logger.info("指定路線データは取得済みのためスキップ kind=%s pref=%s path=%s", kind, pref, dest)
        return dest

    url = _zip_url(kind, pref)
    tmp_dest = dest.with_suffix(".zip.part")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        async with client.stream("GET", url, timeout=httpx.Timeout(60.0)) as response:
            response.raise_for_status()
            with open(tmp_dest, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
        tmp_dest.replace(dest)
    except httpx.HTTPError as exc:
        logger.warning("指定路線データ取得に失敗しました kind=%s pref=%s url=%s error=%r", kind, pref, url, exc)
        tmp_dest.unlink(missing_ok=True)
        return None
    return dest


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
        pos_list_el = curve.find(".//gml:posList", _GML_NS)
        if curve_id is None or pos_list_el is None or not (pos_list_el.text or "").strip():
            continue
        values = [float(v) for v in pos_list_el.text.split()]
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


def _parse_n12_geojson(json_bytes: bytes) -> list[tuple[str | None, list[tuple[float, float]]]]:
    """N12の素のGeoJSONから (路線名, [(lon, lat), ...]) のリストを返す。"""
    data = json.loads(json_bytes)
    features: list[tuple[str | None, list[tuple[float, float]]]] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        coords = [(float(lon), float(lat)) for lon, lat in geometry["coordinates"]]
        if len(coords) < 2:
            continue
        name = (feature.get("properties") or {}).get("N12_004")
        features.append((name, coords))
    return features


def extract_features(zip_path: Path, kind: str, pref: str) -> list[tuple[str | None, list[tuple[float, float]]]]:
    """ZIP内の該当ファイル（N10=xml, N12=geojson）を展開しパースする（メモリ上、
    抽出ファイルをディスクへ書かない）。"""
    if kind == "emergency_transport":
        member_name = f"N10-15_{pref}.xml"
        parser = _parse_n10_gml
    else:
        member_name = f"N12-21_{pref}.geojson"
        parser = _parse_n12_geojson

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member_name) as f:
            return parser(f.read())


async def run_import(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    sqlalchemy_url = database_url or settings.database_url

    zip_paths: dict[tuple[str, str], Path] = {}
    async with httpx.AsyncClient() as client:
        for kind in ("emergency_transport", "critical_logistics"):
            for pref in KANTO_PREFECTURE_CODES_KSJ:
                path = await _download_zip(client, kind, pref)
                if path is not None:
                    zip_paths[(kind, pref)] = path

    if not zip_paths:
        logger.error("取得できた指定路線データが1件もありません")
        return 1

    if dry_run:
        total = 0
        for (kind, pref), path in sorted(zip_paths.items()):
            count = len(extract_features(path, kind, pref))
            total += count
            logger.info("dry-run kind=%s pref=%s: %d件", kind, pref, count)
        logger.info("dry-run完了: matched=%d elapsed=%.1fs（DB書き込みなし）", total, time.perf_counter() - started)
        return 0

    engine = create_async_engine(sqlalchemy_url)
    try:
        await create_tables(engine)
        await apply_pending_migrations(engine)
    finally:
        await engine.dispose()

    dsn = sqlalchemy_url.replace("+asyncpg", "").replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")
    conn = await asyncpg.connect(dsn)
    total_inserted = 0
    try:
        for (kind, pref), path in sorted(zip_paths.items()):
            run_started_at = datetime.now(timezone.utc)
            source = _source_for_kind(kind)
            run_id = await conn.fetchval(
                "INSERT INTO designation_import_runs (kind, source, status, started_at) "
                "VALUES ($1, $2, 'running', $3) RETURNING id",
                kind, source, run_started_at,
            )
            try:
                features = extract_features(path, kind, pref)
                await conn.execute(_DELETE_SQL, kind, pref)
                for name, coords in features:
                    await conn.execute(
                        _INSERT_SQL, kind, name, pref, source, LineString(coords).wkb, run_started_at
                    )
                total_inserted += len(features)
                await conn.execute(
                    "UPDATE designation_import_runs SET status='succeeded', finished_at=$2, designation_count=$3 "
                    "WHERE id=$1",
                    run_id, datetime.now(timezone.utc), len(features),
                )
                logger.info(
                    "取込完了 kind=%s pref=%s matched=%d elapsed=%.1fs",
                    kind, pref, len(features), time.perf_counter() - started,
                )
            except BaseException:
                await conn.execute(
                    "UPDATE designation_import_runs SET status='failed', finished_at=$2 WHERE id=$1",
                    run_id, datetime.now(timezone.utc),
                )
                raise
    finally:
        await conn.close()

    logger.info("全件取込完了: inserted=%d elapsed=%.1fs", total_inserted, time.perf_counter() - started)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="KSJ N10/N12→PostGIS取込バッチ（外部静的データソース T51）"
    )
    parser.add_argument("--database-url", default=None, help="取込先DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数集計のみでDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run_import(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
