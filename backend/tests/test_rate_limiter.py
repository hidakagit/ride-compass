"""`infrastructure/rate_limiter.py`——プロセス内の固定窓レート制限。

ここで見ないもの:
- 超過をHTTPの429へ翻訳する層とキーの組み立て → `api/dependencies.py`を通る各ルーターのテスト
- レート制限のキーになるクライアントidの決め方 → `test_client_ip_behind_proxy.py`

**実時間を待たない。** 窓の長さと掃除の間隔はモジュールが読む時計だけで決まるため、その
時計ごと差し替えて進める。掃除が走ったかどうかは辞書の鍵にしか現れないので、そこだけは
モジュールの内部状態を読む。
"""

from collections import defaultdict

import pytest

from app.infrastructure import rate_limiter


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self._now = now

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """時計と集計を差し替える。集計はモジュール大域なので、戻さないと他のテストへ漏れる。"""
    fake = FakeClock()
    monkeypatch.setattr(rate_limiter, "time", fake)
    monkeypatch.setattr(rate_limiter, "_hits", defaultdict(list))
    monkeypatch.setattr(rate_limiter, "_last_sweep", fake.monotonic())
    return fake


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
    def test_a_hit_still_inside_the_window_counts(self, clock):
        assert rate_limiter.check_rate_limit("a", 1) is True
        clock.advance(rate_limiter._WINDOW_SECONDS - 1)

        assert rate_limiter.check_rate_limit("a", 1) is False

    def test_a_hit_that_is_exactly_a_window_old_no_longer_counts(self, clock):
        """境界を内側へ倒すと、窓ぶんきっかり待って再試行した利用者が1回ぶん損をする。"""
        assert rate_limiter.check_rate_limit("a", 1) is True
        clock.advance(rate_limiter._WINDOW_SECONDS)

        assert rate_limiter.check_rate_limit("a", 1) is True

    def test_a_refusal_does_not_extend_the_window(self, clock):
        """拒否もヒットとして数えると、連打をやめない利用者は窓が明けても回復できず、
        タイルも天候も返らないまま固まる。
        """
        for _ in range(3):
            rate_limiter.check_rate_limit("a", 3)
        clock.advance(1)
        for _ in range(5):
            assert rate_limiter.check_rate_limit("a", 3) is False
        clock.advance(rate_limiter._WINDOW_SECONDS - 1)

        assert rate_limiter.check_rate_limit("a", 3) is True


class TestForgettingClientsThatWentAway:
    def test_a_sweep_drops_clients_with_no_recent_hits_and_keeps_the_others(self, clock):
        """鍵はアクセスが止まった後も残るため、掃除が効かないとIPを変えられた数だけ
        辞書が伸び続ける。逆に現役の履歴まで捨てると、上限に達していた利用者が掃除の
        瞬間に回復する。
        """
        rate_limiter.check_rate_limit("gone", 1)
        clock.advance(rate_limiter._SWEEP_INTERVAL_SECONDS)

        assert rate_limiter.check_rate_limit("still-here", 1) is True
        assert "gone" not in rate_limiter._hits
        assert rate_limiter.check_rate_limit("still-here", 1) is False

    def test_nothing_is_swept_before_the_interval_has_passed(self, clock):
        """毎回走らせると、鍵が増えるほど全リクエストが辞書全件の走査を払う。"""
        rate_limiter.check_rate_limit("gone", 1)
        clock.advance(rate_limiter._SWEEP_INTERVAL_SECONDS - 1)
        rate_limiter.check_rate_limit("other", 1)

        assert "gone" in rate_limiter._hits
