"""`infrastructure/rate_limiter.py`——プロセス内の移動窓レート制限。

ここで見ないもの:
- 超過をHTTPの429へ翻訳する層とキーの組み立て → `api/rate_limit.py`を通る各ルーターのテスト
- レート制限のキーになるクライアントidの決め方 → `test_client_ip_behind_proxy.py`
- 来なくなった接続元の記録が消えること → cachetoolsの`TTLCache`が持つ（期限は窓の長さ）。
  記録の中身は入口の結果に現れないので見ない

**実時間を待たない。** 窓の長さはモジュールが読む時計だけで決まるため、`conftest.py`の
`rate_limit_clock`（テストごとに1窓ぶん進んだ状態で始まる）を進める。
"""

from app.infrastructure import rate_limiter


class TestTheLimit:
    def test_requests_up_to_the_limit_are_allowed(self):
        allowed = [rate_limiter.check_rate_limit("a", 3) for _ in range(3)]

        assert allowed == [True, True, True]

    def test_the_request_after_the_limit_is_refused(self):
        for _ in range(3):
            rate_limiter.check_rate_limit("a", 3)

        assert rate_limiter.check_rate_limit("a", 3) is False

    def test_each_client_has_its_own_budget(self):
        """1つのキーへ相乗りさせると、1人が上限に達した瞬間に全員が429になる。"""
        for _ in range(3):
            rate_limiter.check_rate_limit("a", 3)

        assert rate_limiter.check_rate_limit("b", 3) is True


class TestTheWindow:
    def test_a_hit_still_inside_the_window_counts(self, rate_limit_clock):
        assert rate_limiter.check_rate_limit("a", 1) is True
        rate_limit_clock.advance(rate_limiter._WINDOW_SECONDS - 1)

        assert rate_limiter.check_rate_limit("a", 1) is False

    def test_a_hit_that_is_exactly_a_window_old_no_longer_counts(self, rate_limit_clock):
        """境界を内側へ倒すと、窓ぶんきっかり待って再試行した利用者が1回ぶん損をする。"""
        assert rate_limiter.check_rate_limit("a", 1) is True
        rate_limit_clock.advance(rate_limiter._WINDOW_SECONDS)

        assert rate_limiter.check_rate_limit("a", 1) is True

    def test_only_the_hits_that_left_the_window_stop_counting(self, rate_limit_clock):
        """窓を出た分だけが空く。まとめて忘れると、上限に達していた利用者が窓の途中で回復する。"""
        rate_limiter.check_rate_limit("a", 2)
        rate_limit_clock.advance(rate_limiter._WINDOW_SECONDS / 2)
        rate_limiter.check_rate_limit("a", 2)
        rate_limit_clock.advance(rate_limiter._WINDOW_SECONDS / 2)

        assert rate_limiter.check_rate_limit("a", 2) is True
        assert rate_limiter.check_rate_limit("a", 2) is False

    def test_a_refusal_does_not_extend_the_window(self, rate_limit_clock):
        """拒否もヒットとして数えると、連打をやめない利用者は窓が明けても回復できず、
        タイルも天候も返らないまま固まる。
        """
        for _ in range(3):
            rate_limiter.check_rate_limit("a", 3)
        rate_limit_clock.advance(1)
        for _ in range(5):
            assert rate_limiter.check_rate_limit("a", 3) is False
        rate_limit_clock.advance(rate_limiter._WINDOW_SECONDS - 1)

        assert rate_limiter.check_rate_limit("a", 3) is True
