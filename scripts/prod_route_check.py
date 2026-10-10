"""本番のbackendでルートを1本作り、レンズで塗る値がルートの区間に載っているかを見る
（`.github/workflows/deploy-backend.yml`がデプロイのあとに、`.github/workflows/prod-route-check.yml`が1日1回呼ぶ）。

    python scripts/prod_route_check.py

利用者の画面と同じAPIを外から通す: 軸カタログを1回 → 画面の既定の条件で生成を1回 → 終わるまで結果を聞く。
候補が0件か、カタログのどれかの軸について、候補1のどの区間もその軸のレンズが塗る値を持たなければ、理由を出して
終了コード1で終わる。本番には書き込まない（生成の結果はbackendのメモリに置かれ、期限が来ると消える）。
何を見るか・上限の根拠は docs/architecture/tech-stack.md「本番でルートを作る確かめ」。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: 本番のbackend（docs/architecture/tech-stack.md「本番の宛先」）。
PRODUCTION_BACKEND = "https://193-123-166-150.sslip.io"
#: 画面の既定の生成条件（候補数・許容幅・巡航速度・道の除外）。backendのOpenAPIの生成物で、画面も同じものを読む。
GENERATE_CONFIG = Path(__file__).resolve().parents[1] / "frontend/src/types/generated/route-generate-config.json"
#: 起点（緯度, 経度）。取込範囲の中の決まった地点で、毎回同じ所を作る。
START_POINT = (35.7597, 139.7387)
DISTANCE_KM = 15.0
#: 生成を頼んでから結果が出るまで待つ上限（秒）。超えたら失敗にする。
GENERATION_LIMIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 1.0
#: 1回の要求の上限（秒）。backendが応答しないまま止まったときに、待ちの上限を越えて待たない。
REQUEST_TIMEOUT_SECONDS = 30
JST = timezone(timedelta(hours=9))


def generation_request(config: dict, now: datetime) -> dict:
    """画面の既定の条件の生成の要求。重みは送らず、backendの既定の重みで作らせる。"""
    return {
        "latitude": START_POINT[0],
        "longitude": START_POINT[1],
        "distance_km": DISTANCE_KM,
        "distance_tolerance_km": config["default_distance_tolerance_km"],
        "hard_filters": {
            item["key"]: item["key"] in config["hard_filters"]["defaults"] for item in config["hard_filters"]["filters"]
        },
        "max_routes": config["default_max_routes"],
        "assumed_speed_kmh": config["default_assumed_speed_kmh"],
        "start_time": now.astimezone(JST).isoformat(timespec="seconds"),
    }


def painted_value(axis: dict, segment: dict) -> float | None:
    """ルートの区間をその軸のレンズで塗るときの値。どの値で塗るかは軸カタログの`map_paint.value`が決める
    （材料の生値なら`material_values`、ほかは`axis_difficulties`）。値が無ければNone。"""
    value = axis["map_paint"]["value"]
    if value["kind"] == "signed_material":
        return segment.get("material_values", {}).get(value["material"])
    return segment.get("axis_difficulties", {}).get(axis["axis_id"])


def problems(catalog: dict, result: dict) -> list[str]:
    """生成の結果のうち、利用者に見える壊れ（候補が無い・レンズで塗ると全区間が「データなし」になる軸）。"""
    routes = result["routes"]
    if not routes:
        return [f"候補が0件（理由: {result.get('no_candidates_reason')}）"]
    segments = routes[0]["segments"]
    axes = catalog["axes"]
    if not axes:
        return ["軸カタログに軸が無い"]
    return [
        f"「{axis['label']}」（{axis['axis_id']}）: 候補1の区間 {len(segments)} 件のどれにも、レンズが塗る値が無い"
        for axis in axes
        if all(painted_value(axis, segment) is None for segment in segments)
    ]


def _request(method: str, url: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.load(response)


def generate(origin: str, body: dict) -> dict:
    """生成を頼み、終わるまで結果を聞く。失敗・上限超えは例外にする。"""
    started = time.monotonic()
    job = _request("POST", f"{origin}/api/routes/generate", body)
    polls = 0
    while True:
        elapsed = time.monotonic() - started
        if elapsed > GENERATION_LIMIT_SECONDS:
            raise RuntimeError(f"生成が{GENERATION_LIMIT_SECONDS}秒で終わらない（結果を聞いた回数 {polls}）")
        time.sleep(POLL_INTERVAL_SECONDS)
        state = _request("GET", f"{origin}/api/routes/generate/{job['job_id']}")
        polls += 1
        if state["status"] == "done":
            print(f"生成 {time.monotonic() - started:.1f}秒（結果を聞いた回数 {polls}）")
            return state["result"]
        if state["status"] == "failed":
            raise RuntimeError(f"生成が失敗した: {state['error']}")


def main() -> int:
    config = json.loads(GENERATE_CONFIG.read_text(encoding="utf-8"))
    catalog = _request("GET", f"{PRODUCTION_BACKEND}/api/axis-catalog")
    try:
        result = generate(PRODUCTION_BACKEND, generation_request(config, datetime.now(JST)))
    except RuntimeError as error:
        print(f"失敗: {error}")
        return 1
    found = problems(catalog, result)
    for line in found:
        print(f"失敗: {line}")
    if found:
        return 1
    print(f"通った: 候補 {len(result['routes'])} 件・軸 {len(catalog['axes'])} 本のどれも、候補1の区間に塗る値がある")
    return 0


if __name__ == "__main__":
    sys.exit(main())
