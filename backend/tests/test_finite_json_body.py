"""`api/finite_json_body.py`——要求の本文のNaN・無限大を、どの経路でも422で断る入口。

確かめるのは、アプリ（`app.main.app`）へ送った本文のどこに非有限の数があっても、経路の処理へ届く前に
422で断られ、応答がその場所を指すこと。経路は1本（ルート生成）で通す——断るのはアプリの全経路に掛かる
依存1つで、経路ごとの違いは無い。

ここで見ないもの: 有限の数だけの本文が通ること（どの経路のテストも有限の本文で通している）
"""

import httpx
import pytest

from app.main import app


@pytest.mark.parametrize(("body", "loc"), [
    # 範囲の制約を持つ欄。前は検証エラーの応答へNaNを書けずに500だった
    ('{"latitude": 35.6, "longitude": 139.7, "distance_km": NaN}', ["body", "distance_km"]),
    # 辞書の中
    ('{"latitude": 35.6, "longitude": 139.7, "distance_km": 4.0, "route_preference": {"axis": Infinity}}',
     ["body", "route_preference", "axis"]),
    # 並びの中
    ('{"latitude": 35.6, "longitude": 139.7, "distance_km": 4.0, "waypoints": [{"latitude": -Infinity, "longitude": 139.7}]}',
     ["body", "waypoints", 0, "latitude"]),
])
async def test_a_non_finite_number_anywhere_in_the_body_is_refused_with_its_place(body, loc):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/routes/generate", content=body, headers={"content-type": "application/json"}
        )

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [loc]
