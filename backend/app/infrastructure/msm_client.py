"""気象庁MSM（メソ数値予報モデル）の予報値をローカルの`.om`ファイルから読む。

Open-MeteoがAWS Open Data経由で公開している前処理済みMSM（CC-BY-4.0）を定期的に
ローカルへ同期し、読み出しはファイルから直接行う。予報の参照ごとに外部APIを叩かない
ため、レート制限・クォータの制約を受けない。

配信元は変数ごとに「チャンク」（一定時間ぶんを1ファイルにまとめたもの。日本全域・
`chunk_time_length`時間）を持ち、最新runの内容は現在時刻を含むチャンクへ随時書き込まれる。
格子の幾何・チャンクの長さ・データの終端はすべて配信元の`static/meta.json`から取得し、
このモジュールに定数として書き写さない（配信元の変更がエラーにならないまま静かに
誤った値へ化けることを防ぐ）。
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
from omfiles import OmFileReader

from app.config import settings
from app.domain.msm import MsmGrid, interpolate_points, parse_bbox
from app.infrastructure.debug_log import error_type_label, log_external_call

logger = logging.getLogger("app.infrastructure.msm_client")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
MSM_DIR = DATA_DIR / "msm"
_META_FILE = MSM_DIR / "meta.json"
_ETAGS_FILE = MSM_DIR / "etags.json"

JST = ZoneInfo("Asia/Tokyo")

# 風グリッド・ルート評価が使う変数。増やすと同期量がそのぶん増えるため、実際に消費する
# ものだけを並べる。
WIND_VARIABLES: tuple[str, ...] = ("wind_u_component_10m", "wind_v_component_10m", "precipitation")


class MsmUnavailableError(RuntimeError):
    """同期がまだ済んでいない・データが古すぎる等でMSMを読めない状態。"""


def _chunk_path(variable: str, chunk_number: int) -> Path:
    return MSM_DIR / variable / f"chunk_{chunk_number}.om"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update_interval_seconds(default: int = 3 * 60 * 60) -> int:
    """配信元のrun更新間隔。MSM由来の派生値をキャッシュするTTLの基準になる（これより長く
    保持すると新しいrunが出ても古い値を返し続ける）。未同期のときは既定値を返す。"""
    value = _load_json(_META_FILE).get("update_interval_seconds")
    return int(value) if isinstance(value, (int, float)) and value > 0 else default


def _chunk_number(timestamp: int, chunk_hours: int) -> int:
    return int(timestamp // 3600) // chunk_hours


def _chunk_start(chunk_number: int, chunk_hours: int) -> int:
    return chunk_number * chunk_hours * 3600


async def _fetch_meta(client: httpx.AsyncClient) -> dict:
    url = f"{settings.msm_base_url}/static/meta.json"
    with log_external_call("msm:meta") as fields:
        try:
            response = await client.get(url)
            response.raise_for_status()
            meta = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            raise
        fields["result"] = "ok"
        fields["status"] = response.status_code
        return meta


async def _download_chunk(client: httpx.AsyncClient, variable: str, chunk_number: int, etags: dict) -> bool:
    """1チャンクを取得する。配信元の内容が前回と同じなら（304）何もせずFalseを返す。"""
    path = _chunk_path(variable, chunk_number)
    key = f"{variable}/{chunk_number}"
    headers = {}
    etag = etags.get(key)
    if etag is not None and path.exists():
        headers["If-None-Match"] = etag

    url = f"{settings.msm_base_url}/{variable}/chunk_{chunk_number}.om"
    with log_external_call("msm:chunk", variable=variable, chunk=chunk_number) as fields:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 304:
                fields["result"] = "ok"
                fields["status"] = 304
                fields["cache"] = "hit"
                return False
            response.raise_for_status()
            content = response.content
        except httpx.HTTPError as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            raise
        fields["result"] = "ok"
        fields["status"] = response.status_code
        fields["cache"] = "miss"
        fields["bytes"] = len(content)

    def write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".om.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    await asyncio.to_thread(write)
    if response.headers.get("ETag"):
        etags[key] = response.headers["ETag"]
    return True


def _prune(keep: set[Path]) -> None:
    """予報に使わなくなった過去チャンクを消す。1ファイル十数MBのため放置すると増え続ける。"""
    for variable in WIND_VARIABLES:
        directory = MSM_DIR / variable
        if not directory.is_dir():
            continue
        for path in directory.glob("chunk_*.om"):
            if path not in keep:
                path.unlink(missing_ok=True)


async def refresh(client: httpx.AsyncClient, horizon_hours: int | None = None) -> int:
    """配信元と同期する。実際に取得したファイル数を返す。

    現在時刻から`horizon_hours`先までを覆うチャンク（通常1〜2個）を変数ごとに取得する。
    内容が変わっていないチャンクはETagによる条件付きGETで転送自体が起きない。
    """
    horizon = horizon_hours if horizon_hours is not None else settings.msm_forecast_hours
    meta = await _fetch_meta(client)
    chunk_hours = int(meta["chunk_time_length"])
    now = int(time.time())
    chunk_numbers = sorted({_chunk_number(now, chunk_hours), _chunk_number(now + horizon * 3600, chunk_hours)})

    etags = _load_json(_ETAGS_FILE)
    downloaded = 0
    keep: set[Path] = set()
    for variable in WIND_VARIABLES:
        for chunk_number in chunk_numbers:
            keep.add(_chunk_path(variable, chunk_number))
            if await _download_chunk(client, variable, chunk_number, etags):
                downloaded += 1

    MSM_DIR.mkdir(parents=True, exist_ok=True)
    _META_FILE.write_text(json.dumps(meta), encoding="utf-8")
    # 消したチャンクのETagが残ると、次に同じ番号を引いたとき「変更なし」と誤判定して
    # 存在しないファイルを読みに行くため、保持するチャンクぶんだけを残す。
    valid = {f"{variable}/{number}" for variable in WIND_VARIABLES for number in chunk_numbers}
    _ETAGS_FILE.write_text(json.dumps({k: v for k, v in etags.items() if k in valid}), encoding="utf-8")
    await asyncio.to_thread(_prune, keep)

    reference = datetime.fromtimestamp(int(meta["last_run_initialisation_time"]), JST)
    logger.info(
        "MSM同期完了 取得=%d件 最新run=%s 予報終端=%s",
        downloaded,
        reference.strftime("%Y-%m-%d %H:%M"),
        datetime.fromtimestamp(int(meta["data_end_time"]), JST).strftime("%Y-%m-%d %H:%M"),
    )
    return downloaded


def _read_block(variable: str, chunk_number: int, i0: int, i1: int, j0: int, j1: int, t0: int, t1: int) -> np.ndarray:
    path = _chunk_path(variable, chunk_number)
    if not path.exists():
        raise MsmUnavailableError(f"MSMのチャンクが未同期です: {path.name}")
    with OmFileReader(str(path)) as reader:
        return np.asarray(reader[i0:i1, j0:j1, t0:t1], dtype=np.float64)


def _grid_from_meta(meta: dict, n_lat: int, n_lon: int) -> MsmGrid:
    return MsmGrid.from_bbox_and_shape(parse_bbox(meta["crs_wkt"]), n_lat, n_lon)


def _read_series_sync(
    latitudes: np.ndarray, longitudes: np.ndarray, hours: int, now: int
) -> tuple[list[str], dict[str, np.ndarray]]:
    meta = _load_json(_META_FILE)
    if not meta:
        raise MsmUnavailableError("MSMのメタ情報が未同期です")
    chunk_hours = int(meta["chunk_time_length"])
    data_end = int(meta["data_end_time"])

    start = (now // 3600) * 3600
    end = min(start + hours * 3600, data_end)
    if end <= start:
        raise MsmUnavailableError("MSMの予報データが現在時刻に追いついていません")

    # 形状は実データから読む（緯度・経度方向の格子点数を定数として持たないため）。
    sample_path = _chunk_path(WIND_VARIABLES[0], _chunk_number(start, chunk_hours))
    if not sample_path.exists():
        raise MsmUnavailableError(f"MSMのチャンクが未同期です: {sample_path.name}")
    with OmFileReader(str(sample_path)) as reader:
        n_lat, n_lon = int(reader.shape[0]), int(reader.shape[1])
    grid = _grid_from_meta(meta, n_lat, n_lon)
    i0, i1, j0, j1 = grid.slice_bounds(latitudes, longitudes)

    series: dict[str, list[np.ndarray]] = {variable: [] for variable in WIND_VARIABLES}
    times: list[str] = []
    cursor = start
    while cursor < end:
        chunk_number = _chunk_number(cursor, chunk_hours)
        chunk_begin = _chunk_start(chunk_number, chunk_hours)
        t0 = (cursor - chunk_begin) // 3600
        t1 = min((end - chunk_begin) // 3600, chunk_hours)
        for variable in WIND_VARIABLES:
            block = _read_block(variable, chunk_number, i0, i1, j0, j1, t0, t1)
            series[variable].append(interpolate_points(block, grid, i0, j0, latitudes, longitudes))
        times.extend(
            datetime.fromtimestamp(chunk_begin + hour * 3600, JST).strftime("%Y-%m-%dT%H:%M") for hour in range(t0, t1)
        )
        cursor = chunk_begin + t1 * 3600

    return times, {variable: np.concatenate(parts, axis=1) for variable, parts in series.items()}


async def read_series(
    latitudes: np.ndarray, longitudes: np.ndarray, hours: int | None = None
) -> tuple[list[str], dict[str, np.ndarray]]:
    """地点ごとの時系列（現在時刻の正時から`hours`時間ぶん）を返す。

    戻り値は(時刻列, 変数ごとの[地点数, 時刻数]配列)。時刻はJSTのISO文字列
    （分まで、タイムゾーン指定なし）で、フロントの既存パーサの入力形式と揃える。
    同期が済んでいない・予報が現在時刻へ追いついていない場合は`MsmUnavailableError`。
    """
    requested = hours if hours is not None else settings.msm_forecast_hours
    with log_external_call("msm:read", locations=len(latitudes), hours=requested) as fields:
        fields["cache"] = "hit"
        try:
            result = await asyncio.to_thread(_read_series_sync, latitudes, longitudes, requested, int(time.time()))
        except (MsmUnavailableError, OSError, ValueError, KeyError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            raise
        fields["result"] = "ok"
        fields["times"] = len(result[0])
        return result
