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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
from shapely.geometry import LineString
from sqlalchemy.ext.asyncio import create_async_engine

from app.batch._common import asyncpg_dsn, download_to_path, reap_stale_running_import_runs
from app.config import settings
from app.domain.designation import DESIGNATION_IMPORT_KINDS
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


async def _download_zip(client: httpx.AsyncClient, kind: str, pref: str) -> Path | None:
    """都道府県別ZIPを直接取得しDATA_DIRへ保存する（改善計画T80、骨格は
    app/batch/_common.py: download_to_pathへ共通化済み）。"""
    dest = DATA_DIR / f"{kind}_{pref}.zip"
    url = _zip_url(kind, pref)
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
        # JPGISでは1つのgml:Curveが複数のgml:LineStringSegment（＝複数posList）を持ちうる
        # （改善計画T72）。findで最初の1つだけ読むと2番目以降が無警告で切り捨てられ、
        # 件数は合うままバッファ交差率だけが縮んで後半区間が指定路線と判定されなくなる。
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
    """LineString/MultiLineString双方から素の座標配列のリストを返す（改善計画T72、
    MultiLineStringのfeatureが無警告でスキップされ路線が黙って欠落する問題への対応）。
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
            # （改善計画T72。3要素のままunpackするとValueErrorでrun全体が異常終了していた）。
            coords = [(float(c[0]), float(c[1])) for c in raw_coords]
            if len(coords) < 2:
                continue
            features.append((name, coords))
    if skipped_types:
        logger.warning("N12ジオメトリのうち非対応typeをスキップしました types=%s", skipped_types)
    return features


@dataclass(frozen=True)
class _DesignationKindSpec:
    """kind→(取得URL・DB上のsource値・ZIP内メンバー名・パーサ)の対応（改善計画T75）。

    以前はこの対応がURL組み立て・source文字列・ZIPメンバー名解決の3関数へ平行分岐で
    分散し、いずれもelse側が暗黙にN12扱いへ倒れていた（kind追加時の編集漏れが静かに壊れる）。
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


def extract_features(zip_path: Path, kind: str, pref: str) -> list[tuple[str | None, list[tuple[float, float]]]]:
    """ZIP内の該当ファイル（N10=xml, N12=geojson）を展開しパースする（メモリ上、
    抽出ファイルをディスクへ書かない）。"""
    spec = _KIND_SPECS[kind]
    member_name = spec.member_template.format(pref=pref)

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member_name) as f:
            return spec.parser(f.read())


async def _write_designations(
    conn: asyncpg.Connection,
    kind: str,
    pref: str,
    source: str,
    features: list[tuple[str | None, list[tuple[float, float]]]],
    run_started_at: datetime,
) -> int:
    """(kind, pref)単位でDELETE→INSERTを1トランザクションに括り、featuresが0件のときは
    DELETEごとスキップする（改善計画T71）。

    従来はDELETEと各INSERTがトランザクション外（asyncpgのautocommitで1文ずつ確定）で、
    かつパーサが0件を返した場合もDELETEだけが実行され既存データが静かに消えていた。
    0件時に何もしないことで、パーサの異常・取得データの一時的欠落がその都道府県の
    既存指定路線を全消しする事故を防ぐ。
    """
    if not features:
        logger.warning(
            "指定路線データが0件のため取込をスキップします（既存データは保持） kind=%s pref=%s", kind, pref
        )
        return 0
    async with conn.transaction():
        await conn.execute(_DELETE_SQL, kind, pref)
        await conn.executemany(
            _INSERT_SQL,
            [(kind, name, pref, source, LineString(coords).wkb, run_started_at) for name, coords in features],
        )
    return len(features)


async def run_import(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    sqlalchemy_url = database_url or settings.database_url

    zip_paths: dict[tuple[str, str], Path] = {}
    async with httpx.AsyncClient() as client:
        for kind in DESIGNATION_IMPORT_KINDS:
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

    conn = await asyncpg.connect(asyncpg_dsn(sqlalchemy_url))
    total_inserted = 0
    try:
        # 改善計画T467: 前回実行がプロセスクラッシュでrunning状態のまま取り残されていないか
        # 確認し、あれば自己修復する（_common.py: reap_stale_running_import_runs参照）。
        reaped = await reap_stale_running_import_runs(conn, "designation_import_runs")
        if reaped:
            logger.warning(
                "クラッシュで取り残されたrunning状態のdesignation_import_runsを%d件failedへ遷移しました", reaped
            )
        for (kind, pref), path in sorted(zip_paths.items()):
            run_started_at = datetime.now(timezone.utc)
            source = _KIND_SPECS[kind].source
            run_id = await conn.fetchval(
                "INSERT INTO designation_import_runs (kind, source, status, started_at) "
                "VALUES ($1, $2, 'running', $3) RETURNING id",
                kind, source, run_started_at,
            )
            try:
                features = extract_features(path, kind, pref)
                insert_started = time.perf_counter()
                count = await _write_designations(conn, kind, pref, source, features, run_started_at)
                insert_elapsed = time.perf_counter() - insert_started
                total_inserted += count
                await conn.execute(
                    "UPDATE designation_import_runs SET status='succeeded', finished_at=$2, designation_count=$3 "
                    "WHERE id=$1",
                    run_id, datetime.now(timezone.utc), count,
                )
                log = logger.warning if count == 0 else logger.info
                log(
                    "取込完了 kind=%s pref=%s matched=%d insert_elapsed=%.1fs elapsed=%.1fs",
                    kind, pref, count, insert_elapsed, time.perf_counter() - started,
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
