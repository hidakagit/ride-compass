"""`services/tuning_service.py`——較正値の上書きの取引の区切りと、書いた値をプロセスへ反映するところ。

ここで見ないもの:
- 上書きの行の読み書き・範囲の外や数値でない値の判定・プロセス内の値の組み立て → `test_tuning_overrides.py`
- HTTPの受け口（404・422への写し替え・一覧の並び） → `test_tuning_admin_routes.py`

下の読み書き（`infrastructure/tuning_overrides.py`）とセッションは、呼ばれた順を1本の記録へ残す代役へ
差し替える。下の関数の代役は本物の署名へ当てる（`bound`）。
"""

import pytest

from app.services import tuning_service
from tests.bound_fake import bound


class Session:
    """取引の区切りを記録するセッションの代役。"""

    def __init__(self, events: list, fail_on_commit: bool = False):
        self.events = events
        self.fail_on_commit = fail_on_commit

    async def commit(self):
        if self.fail_on_commit:
            raise RuntimeError("commitできない")
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


@pytest.fixture
def events(monkeypatch):
    """下の読み書きを代役へ差し替え、呼ばれた順を返す。`failing`へ名前を入れるとその段が失敗する。"""
    recorded: list = []
    failing: set[str] = set()

    def stub(name, result=None):
        async def call(session, *args):
            if name in failing:
                raise RuntimeError(f"{name}できない")
            recorded.append((name, *args))
            return result

        monkeypatch.setattr(tuning_service, name, bound(getattr(tuning_service, name), call))

    stub("read_overrides", {"speed.crr": 0.006, "turn.right_seconds": 9.0})
    stub("set_override")
    stub("clear_override")
    stub("refresh_tuning_values")
    return recorded, failing


async def test_overridden_ids_are_the_ids_that_have_a_row(events):
    assert await tuning_service.overridden_parameter_ids(Session([])) == {"speed.crr", "turn.right_seconds"}


@pytest.mark.parametrize(
    ("value", "write"),
    [
        (0.006, ("set_override", "speed.crr", 0.006)),
        # 値が無ければ既定へ戻す（行を外す）
        (None, ("clear_override", "speed.crr")),
    ],
)
async def test_saving_writes_commits_and_then_refreshes_the_running_values(events, value, write):
    recorded, _ = events
    session = Session(recorded)

    await tuning_service.save_override(session, "speed.crr", value)

    # 反映は取引が確定してから——DBに無い値がプロセスだけで効くことはない
    assert recorded == [write, "commit", ("refresh_tuning_values",)]


@pytest.mark.parametrize(
    ("value", "failing_step"),
    [(0.006, "set_override"), (None, "clear_override"), (0.006, "commit")],
)
async def test_a_failed_save_is_rolled_back_raised_and_not_refreshed(events, value, failing_step):
    recorded, failing = events
    session = Session(recorded, fail_on_commit=failing_step == "commit")
    failing.add(failing_step)

    with pytest.raises(RuntimeError):
        await tuning_service.save_override(session, "speed.crr", value)

    # 半分だけ書けた状態を反映すると、DBと動いている値が食い違う
    assert recorded[-1] == "rollback"
    assert ("refresh_tuning_values",) not in recorded
