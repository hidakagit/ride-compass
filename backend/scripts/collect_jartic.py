"""JARTIC（日本道路交通情報センター）交通量オープンデータの収集（改善計画T53、
docs/external-data-sources-review-2026-08-16.md §4.5）。

評価パイプラインには組み込まない。carStress軸（domain/traffic.py:
car_stress_level）の較正・検証データとして、1回のスナップショット収集→分析で
完結させる（定期収集は較正に不足すると分かった場合のみ検討）。

収集先テーブル（traffic_stations/traffic_hourly）は**dev機PostgreSQLのみに保持**し、
本番Oracle向けの`backend/migrations/`（`infrastructure/migrate.py: apply_pending_migrations`）
には含めない（研究用データを本番に置かない、という外部静的データソースレビュー§4の
共通方針）。そのためテーブル作成もこのスクリプト自身が行う自己完結型にしてある
（`app/infrastructure/road_graph_models.py: Base`へは登録しない）。

データソース: WFS準拠API（登録不要、規約同意のみ）。
    ベースURL: https://api.jartic-open-traffic.org/geoserver
    typeNames: t_travospublic_measure_1h（1時間値。5分値はt_travospublic_measure_5m だが
    過去1ヶ月分しか保持されないため、過去3ヶ月分が取れる1時間値を使う）。
    フィールド名・値は2026-08-17に実データで確認済み（道路種別/時間コード/常時観測点コード/
    上り・下り×小型・大型・車種判別不能交通量/ジオメトリ(MultiPoint)等）。GeoServerの
    バグかWFS 2.0の仕様上の理由か、cql_filterパラメータは省略不可（無いと400を返す）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\collect_jartic.py --date 20260817
    .venv\\Scripts\\python.exe scripts\\collect_jartic.py --date 20260817 --dry-run
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from app.batch._common import asyncpg_dsn  # noqa: E402
from app.config import settings  # noqa: E402

logger = logging.getLogger("scripts.collect_jartic")

JARTIC_BASE_URL = "https://api.jartic-open-traffic.org/geoserver"
JARTIC_TYPE_NAME = "t_travospublic_measure_1h"

# 関東7都県本土（離島除く）のextent。docs/osm-pbf-import.md「取込範囲bboxの決定」で
# PBF取込用に検証済みの候補bbox(34.85,138.35,37.20,140.95、lat/lon順)をJARTIC側の
# BBOX(ジオメトリ, minx, miny, maxx, maxy, 'EPSG:4326')関数が要求するlon/lat順へ変換した値。
DEFAULT_BBOX = (138.35, 34.85, 140.95, 37.20)

# 道路種別='3'は一般道（高速道路等を除く）。carStress軸の対象highwayが自動車専用道路
# ではない道路（residential〜trunk）であることに合わせる。
DEFAULT_ROAD_TYPE = "3"

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS traffic_stations (
    station_id bigint PRIMARY KEY,
    road_type text NOT NULL,
    geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traffic_stations_geom ON traffic_stations USING gist (geom);

CREATE TABLE IF NOT EXISTS traffic_hourly (
    station_id bigint NOT NULL REFERENCES traffic_stations(station_id),
    observed_at timestamptz NOT NULL,
    direction text NOT NULL,
    volume integer NOT NULL,
    PRIMARY KEY (station_id, observed_at, direction)
);
"""

_UPSERT_STATION_SQL = """
INSERT INTO traffic_stations (station_id, road_type, geom)
VALUES ($1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326))
ON CONFLICT (station_id) DO NOTHING
"""

_UPSERT_HOURLY_SQL = """
INSERT INTO traffic_hourly (station_id, observed_at, direction, volume)
VALUES ($1, $2, $3, $4)
ON CONFLICT (station_id, observed_at, direction) DO UPDATE SET volume = EXCLUDED.volume
"""


def build_cql_filter(road_type: str, time_code: str, bbox: tuple[float, float, float, float]) -> str:
    """JARTIC WFSのcql_filterを組み立てる。フィールド名（道路種別/時間コード/ジオメトリ）は
    2026-08-17に実データで確認済み（コード先頭のモジュールdocstring参照）。`時間コード`は
    範囲指定（>=/<=）ではなく単一時刻の完全一致にする（fetch_hour_featuresのdocstring参照）。
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        f"道路種別={road_type} AND "
        f"時間コード={time_code} AND "
        f"BBOX(ジオメトリ,{min_lon},{min_lat},{max_lon},{max_lat},'EPSG:4326')"
    )


async def fetch_hour_features(
    client: httpx.AsyncClient, road_type: str, time_code: str, bbox: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    """指定した1時間ぶん（時間コード完全一致）のフィーチャーを1リクエストで取得する。

    2026-08-17実機確認: このGeoServerデプロイは`count`/`startIndex`パラメータを
    無視し、cql_filterの`時間コード>=...AND...<=...`のような範囲指定で複数時間ぶんを
    一度に要求すると、`numberMatched`が実際の対象件数より小さい値で頭打ちになった
    まま`startIndex`を変えても同一の結果セットが返り続ける（ページングが機能せず、
    素朴なページングループが無限ループ化する）。関東全域・1時間ぶん（実測106件、
    道路種別=3）は`count`指定なしの単発リクエストで頭打ちなく全件返ることを確認済みの
    ため、時間範囲は呼び出し側（collect）で時間ごとに分割し、サーバー側ページングには
    一切頼らない設計にした。
    """
    cql_filter = build_cql_filter(road_type, time_code, bbox)
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": JARTIC_TYPE_NAME,
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
        "exceptions": "application/json",
        "cql_filter": cql_filter,
    }
    started = time.perf_counter()
    response = await client.get(JARTIC_BASE_URL, params=params, timeout=httpx.Timeout(60.0))
    response.raise_for_status()
    data = response.json()
    features = data.get("features", [])
    number_matched = data.get("numberMatched")
    if isinstance(number_matched, int) and number_matched > len(features):
        logger.warning(
            "時間コード=%s: numberMatched(%d)がactual件数(%d)を上回っています（サーバー側の"
            "頭打ちで取りこぼしがある可能性）。bboxを狭めて分割することを検討してください。",
            time_code, number_matched, len(features),
        )
    logger.info(
        "JARTIC取得 時間コード=%s 件数=%d elapsed=%.1fs", time_code, len(features), time.perf_counter() - started
    )
    return features


async def fetch_all_features(
    client: httpx.AsyncClient, road_type: str, date: str, hour_from: int, hour_to: int, bbox: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    """[hour_from, hour_to]の各時間を個別リクエストで取得し結合する（fetch_hour_features
    のdocstring参照）。"""
    features: list[dict[str, Any]] = []
    for hour in range(hour_from, hour_to + 1):
        time_code = f"{date}{hour:02d}00"
        features.extend(await fetch_hour_features(client, road_type, time_code, bbox))
    return features


def parse_feature(feature: dict[str, Any]) -> list[tuple[int, str, float, float, datetime, str, int]] | None:
    """1フィーチャー（1観測点×1時間）を(station_id, road_type, lon, lat, observed_at,
    direction, volume)の上り・下り2レコードへ変換する。ジオメトリはMultiPoint（実データで
    確認済み、単一点のみを持つ）のため先頭座標を使う。小型・大型・車種判別不能の3区分は
    合算する（LTS段階と交通量分布を突き合わせる分析には合計値で足りるため、区分別の
    テーブルは持たない。改善計画T53完了条件参照）。
    """
    props = feature.get("properties", {})
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return None
    # MultiPointは[[lon, lat], ...]、Pointは[lon, lat]。どちらも先頭点を取れば良いよう揃える。
    point = coordinates[0] if geometry.get("type") == "MultiPoint" else coordinates
    lon, lat = point[0], point[1]

    station_id = props.get("常時観測点コード")
    road_type = props.get("道路種別")
    time_code = props.get("時間コード")
    if station_id is None or road_type is None or time_code is None:
        return None
    # 時間コードはYYYYMMDDHHmm（1時間値は分=00固定）で日時を完結して表す。観測年月日＋時間帯
    # からの再構成は「時間帯」の意味（1時間値では常に0で、実際の時刻は時間コード側が持つ）を
    # 誤解しやすいため使わない（実データ確認2026-08-17）。
    observed_at = datetime.strptime(str(time_code), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)

    up_volume = sum(
        int(props.get(key) or 0) for key in ("上り・小型交通量", "上り・大型交通量", "上り・車種判別不能交通量")
    )
    down_volume = sum(
        int(props.get(key) or 0) for key in ("下り・小型交通量", "下り・大型交通量", "下り・車種判別不能交通量")
    )
    return [
        (station_id, road_type, lon, lat, observed_at, "up", up_volume),
        (station_id, road_type, lon, lat, observed_at, "down", down_volume),
    ]


async def collect(
    date: str,
    hour_from: int,
    hour_to: int,
    road_type: str,
    bbox: tuple[float, float, float, float],
    database_url: str | None,
    dry_run: bool,
) -> int:
    started = time.perf_counter()
    async with httpx.AsyncClient() as client:
        raw_features = await fetch_all_features(client, road_type, date, hour_from, hour_to, bbox)

    records: list[tuple[int, str, float, float, datetime, str, int]] = []
    skipped = 0
    for feature in raw_features:
        parsed = parse_feature(feature)
        if parsed is None:
            skipped += 1
            continue
        records.extend(parsed)
    if skipped:
        logger.warning("プロパティ欠損で%d件スキップしました", skipped)

    stations = {(r[0], r[1], r[2], r[3]) for r in records}
    logger.info(
        "取得完了 date=%s hour=%d-%d road_type=%s features=%d stations=%d hourly_records=%d elapsed=%.1fs",
        date, hour_from, hour_to, road_type, len(raw_features), len(stations), len(records),
        time.perf_counter() - started,
    )

    if dry_run:
        logger.info("dry-run完了（DB書き込みなし）")
        return 0
    if not records:
        logger.warning("収集件数が0件のためDB書き込みをスキップします")
        return 1

    sqlalchemy_url = database_url or settings.database_url
    conn = await asyncpg.connect(asyncpg_dsn(sqlalchemy_url))
    try:
        await conn.execute(_CREATE_TABLES_SQL)
        await conn.executemany(
            _UPSERT_STATION_SQL, [(station_id, rt, lon, lat) for station_id, rt, lon, lat in stations]
        )
        await conn.executemany(
            _UPSERT_HOURLY_SQL,
            [(station_id, observed_at, direction, volume) for station_id, _, _, _, observed_at, direction, volume in records],
        )
    finally:
        await conn.close()
    logger.info("DB書き込み完了 stations=%d hourly_records=%d", len(stations), len(records))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
    parser.add_argument("--date", default=yesterday, help="収集対象日（YYYYMMDD、既定: 前日UTC）")
    parser.add_argument("--hour-from", type=int, default=0, help="開始時（0-23、既定0）")
    parser.add_argument("--hour-to", type=int, default=23, help="終了時（0-23、既定23）")
    parser.add_argument("--road-type", default=DEFAULT_ROAD_TYPE, help="JARTIC道路種別（既定'3'=一般道）")
    parser.add_argument(
        "--bbox", default=None, help='"min_lon,min_lat,max_lon,max_lat"（既定: 関東本土7都県）'
    )
    parser.add_argument("--database-url", default=None, help="収集先DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数集計のみでDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bbox = tuple(float(v) for v in args.bbox.split(",")) if args.bbox else DEFAULT_BBOX
    return asyncio.run(
        collect(args.date, args.hour_from, args.hour_to, args.road_type, bbox, args.database_url, args.dry_run)
    )


if __name__ == "__main__":
    sys.exit(main())
