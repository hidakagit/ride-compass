"""`api/rate_limit.py: client_id`が、接続元の分からない要求を共有の1つのキーへ寄せ、そのことを残す。

ここで見ないもの:
- 接続元がある要求のキーと429 → レート制限を持つ経路のテスト（testing-patterns-runtime.md「パターン1」）
- リバースプロキシの後ろで訪問者のIPを接続元にする設定 → `backend/Dockerfile`のuvicornの引数（テストは読まない）
"""

import logging

from fastapi import Request

from app.api.rate_limit import client_id


def test_a_request_without_a_client_falls_back_to_a_shared_key_with_a_warning(caplog):
    request = Request({"type": "http", "client": None, "headers": []})

    with caplog.at_level(logging.WARNING, logger="ridecompass.external"):
        result = client_id(request)

    assert result == "unknown"
    assert any("unknown" in record.message for record in caplog.records)
