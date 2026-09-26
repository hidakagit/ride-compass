"""e2e-live（`frontend/e2e-live/`）のために、この作業ツリーのbackendを開発DBへ向けて起動する。

作業ツリーには`.env`が無い（gitignoreの対象は作業ツリーへ写らない）ので、本体のチェックアウトの`backend/.env`
を読み（DBの向け先・土地被覆ラスタのパス等）、E2Eのオリジンへ向ける2つ——基礎地図のURLとCORSの許可——だけを
足して起動する。ポートは空いているものを選ぶ（並行する担当のbackendと取り合わない）。起点は開発DBの区間から、
路面タイルに道が出る点を選ぶ——開発DBの取込範囲はリポジトリに記録が無く、DBだけが知っている。`/health`が
返り起点が決まったら、ビルドと実行のコマンド（向け先・起点を埋めたもの）を出し、止められるまで動き続ける
（Bashの道具なら裏で走らせ、出力を読む）。

    python backend/scripts/serve_e2e_live.py [--port N] [--point 緯度,経度]

本体の`backend/.venv`のPythonで走らせ直すので、どのPythonで呼んでもよい。前提・手順の正本は
docs/conventions/testing.md パターン4「走らせ方」。
"""

import argparse
import asyncio
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
WORKTREE = BACKEND.parent
#: E2Eのオリジン（`frontend/playwright.live.config.ts`の`LIVE_ORIGIN`）。
LIVE_ORIGIN = "http://localhost:3200"
DEFAULT_PORT = 8000
HEALTH_TIMEOUT_SECONDS = 300
#: 起点の候補にする区間の数。取込範囲の真ん中あたりの区間から順に、路面タイルに道が出るものを探す。
POINT_CANDIDATES = 40


def main_checkout() -> Path:
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=BACKEND,
                            capture_output=True, check=True).stdout.decode("utf-8").strip()
    return Path(common).parent


def venv_python(main: Path) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    return main / "backend" / ".venv" / scripts / ("python.exe" if os.name == "nt" else "python")


def backend_env(main: Path, port: int) -> dict[str, str]:
    """本体の`.env`に、E2Eのオリジンへ向ける値を足した環境。`.env`の値は画面へ出さない。"""
    from dotenv import dotenv_values

    env = dict(os.environ)
    for key, value in dotenv_values(main / "backend" / ".env").items():
        if value is not None:
            env[key.upper()] = value
    env["BASEMAP_PUBLIC_BASE_URL"] = f"{LIVE_ORIGIN}/api/basemap"
    # `settings.cors_allowed_origins_list`はカンマで区切る（JSONの配列ではない）。
    origins = [o.strip() for o in env.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    env["CORS_ALLOWED_ORIGINS"] = ",".join(origins + ([LIVE_ORIGIN] if LIVE_ORIGIN not in origins else []))
    env["PYTHONIOENCODING"] = "utf-8"
    env["PORT"] = str(port)
    return env


def free_port(wanted: int | None) -> int:
    for port in ([wanted] if wanted else [DEFAULT_PORT, 0]):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                if wanted:
                    raise SystemExit(f"{port}番は使われている（--port を外すと空いているポートを選ぶ）") from None
                continue
            return int(s.getsockname()[1])
    raise SystemExit("空いているポートが無い")


def get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return bytes(r.read())
    except (urllib.error.URLError, OSError):
        return None


def wait_health(api: str, proc: subprocess.Popen[bytes], log: Path) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while get(f"{api}/health") is None:
        if proc.poll() is not None:
            raise SystemExit(f"backendが起動しなかった（終了コード{proc.returncode}）。ログ: {log}")
        if time.monotonic() > deadline:
            proc.terminate()
            raise SystemExit(f"{HEALTH_TIMEOUT_SECONDS}秒待っても{api}/healthが返らない。ログ: {log}")
        time.sleep(2)


async def candidate_points(database_url: str) -> list[tuple[float, float]]:
    """開発DBの区間のうち、主キーの順で真ん中あたりの区間の中点（緯度, 経度）。"""
    import asyncpg

    from app.batch._common import asyncpg_dsn

    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        rows = await conn.fetch(
            "SELECT ST_Y(p) AS lat, ST_X(p) AS lon FROM ("
            " SELECT ST_LineInterpolatePoint(geom, 0.5) AS p FROM road_edges ORDER BY osm_way_id, segment_index"
            " OFFSET (SELECT GREATEST(reltuples, 0)::bigint / 2 FROM pg_class WHERE relname = 'road_edges')"
            f" LIMIT {POINT_CANDIDATES}) s")
    finally:
        await conn.close()
    return [(float(r["lat"]), float(r["lon"])) for r in rows]


def tile_of(z: int, lat: float, lon: float) -> tuple[int, int]:
    n = 2**z
    rad = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(rad) + 1 / math.cos(rad)) / math.pi) / 2 * n)


def roads_in_tile(api: str, lat: float, lon: float) -> int:
    """`e2e-live/global-setup.ts`と同じ確かめ方: 最大ズームの路面タイルに道が何本出るか。"""
    import mapbox_vector_tile

    config = json.loads((WORKTREE / "frontend/src/types/generated/region-tile-config.json").read_text(encoding="utf-8"))
    catalog = json.loads(get(f"{api}/api/axis-catalog") or b"{}")
    version = (catalog.get("tile_versions") or {}).get("road_surface")
    z = int(config["road_tile_max_zoom"])
    x, y = tile_of(z, lat, lon)
    body = get(f"{api}/api/region/road-surface-tiles/{z}/{x}/{y}.pbf?v={version}")
    if not body:
        return 0
    layer = mapbox_vector_tile.decode(body).get(config["road_surface"]["layer_name"]) or {}
    return len(layer.get("features") or [])


def choose_point(api: str, env: dict[str, str], given: str | None) -> str:
    if given:
        lat, lon = (float(v) for v in given.split(","))
        if not roads_in_tile(api, lat, lon):
            raise SystemExit(f"起点 {given} の路面タイルに道が無い（開発DBの取込範囲の外）。--point を外すとDBから選ぶ")
        return given
    for lat, lon in asyncio.run(candidate_points(env["DATABASE_URL"])):
        if roads_in_tile(api, lat, lon):
            return f"{lat:.5f},{lon:.5f}"
    raise SystemExit("開発DBの区間から、路面タイルに道が出る起点を選べなかった（--point で与える）")


def main() -> int:
    parser = argparse.ArgumentParser(description="e2e-live用に、作業ツリーのbackendを開発DBへ向けて起動する")
    parser.add_argument("--port", type=int, help=f"待ち受けるポート（既定: {DEFAULT_PORT}、使われていれば空いているもの）")
    parser.add_argument("--point", help="起点（緯度,経度）。既定は開発DBの区間から選ぶ")
    args = parser.parse_args()
    main = main_checkout()
    python = venv_python(main)
    if python.exists() and Path(sys.executable).resolve() != python.resolve():
        return subprocess.call([str(python), __file__, *sys.argv[1:]])
    sys.path.insert(0, str(BACKEND))

    port = free_port(args.port)
    api = f"http://localhost:{port}"
    env = backend_env(main, port)
    log = Path(tempfile.gettempdir()) / f"serve_e2e_live-{port}.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                 "--port", str(port)], cwd=BACKEND, env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        wait_health(api, proc, log)
        point = choose_point(api, env, args.point)
        print(f"backend: {api}（この作業ツリーのコード・開発DB。pid {proc.pid}、ログ {log}）")
        print(f"起点: E2E_LIVE_POINT={point}")
        print("ビルド（向け先はビルドに埋め込まれる）: python scripts/lockrun.py -- "
              f"'cd frontend && NEXT_PUBLIC_API_URL={api} BACKEND_INTERNAL_URL={api} npm run build'")
        print("実行（シナリオごとに1回）: python scripts/lockrun.py -- "
              f"'cd frontend && E2E_LIVE_API={api} E2E_LIVE_POINT={point} "
              "./node_modules/.bin/playwright test -c playwright.live.config.ts e2e-live/<シナリオ>.spec.ts'")
        # 呼び出した側を止めてもbackendの子は残りうる（Windowsは親を止めても子を止めない）ので、pidで止める形を出す。
        print(f"止める: PowerShellで Stop-Process -Id {proc.pid}（この処理も終わる）", flush=True)
        return proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    sys.exit(main())
