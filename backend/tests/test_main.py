from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_cors_is_wired_so_the_browser_can_call_the_api():
    """CORSの結線が外れると、ブラウザからのAPI呼び出しが丸ごと通らなくなる。

    許可・拒否・`x-request-id`の公開はどれも同じ1箇所（`add_middleware`の引数）から
    出るため、1件で見る。
    """
    allowed = settings.cors_allowed_origins_list[0]

    response = client.get("/health", headers={"Origin": allowed})
    rejected = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert response.headers["access-control-allow-origin"] == allowed
    # クロスオリジンではexpose_headersに載せない限りブラウザのJSからヘッダを読めない。
    assert "x-request-id" in response.headers.get("access-control-expose-headers", "").lower()
    assert "access-control-allow-origin" not in rejected.headers
