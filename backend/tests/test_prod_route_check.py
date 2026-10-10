"""`backend/scripts/prod_route_check.py`のテスト（本番・ネットワークには触れない）。

ここで見ないもの: 本番へ要求を送って結果を待つ口（`generate`・`main`）と、ワークフローから呼ぶ所の結線。
待ちの上限はワークフローの段の`timeout-minutes`も持つ。
"""

from datetime import datetime

import pytest

from app.api.routers.routes import RouteGenerateRequest
from scripts import prod_route_check as check

GRADIENT = {
    "axis_id": "gradient",
    "label": "勾配",
    "map_paint": {"value": {"kind": "signed_material", "material": "gradient_percent"}},
}
RAIN = {"axis_id": "rain_24h", "label": "雨", "map_paint": {"value": {"kind": "difficulty"}}}
CATALOG = {"axes": [GRADIENT, RAIN]}


def _result(*segments: dict) -> dict:
    return {"routes": [{"segments": list(segments)}], "no_candidates_reason": None}


def test_generation_request_is_accepted_by_the_api():
    """要求の形がAPIの型に合わないと、本番の確かめが毎回422で落ち、壊れを見張れなくなる。"""
    config = check.json.loads(check.GENERATE_CONFIG.read_text(encoding="utf-8"))
    request = check.generation_request(config, datetime(2026, 10, 10, 7, 0, tzinfo=check.JST))
    RouteGenerateRequest.model_validate(request)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        # 塗る値が1つの区間にでもあれば、その軸は塗れる。
        (
            _result(
                {"material_values": {"gradient_percent": 2.0}, "axis_difficulties": {}},
                {"material_values": {}, "axis_difficulties": {"rain_24h": 10.0}},
            ),
            [],
        ),
        # 勾配のレンズは材料の生値で塗る。難易度だけがあっても全区間が「データなし」になる。
        (
            _result({"material_values": {}, "axis_difficulties": {"gradient": 5.0, "rain_24h": 10.0}}),
            ["「勾配」（gradient）"],
        ),
        # 値の欄そのものが無い区間も、値が無いと読む。
        (_result({}), ["「勾配」（gradient）", "「雨」（rain_24h）"]),
        ({"routes": [], "no_candidates_reason": "道が無い"}, ["候補が0件（理由: 道が無い）"]),
    ],
)
def test_problems(result, expected):
    found = check.problems(CATALOG, result)
    assert len(found) == len(expected)
    for line, head in zip(found, expected, strict=True):
        assert line.startswith(head)


def test_problems_fails_on_an_empty_catalog():
    """軸カタログが空だと、見る軸が無いまま通り、全部の軸が消えた壊れを見逃す。"""
    assert check.problems({"axes": []}, _result({})) != []
