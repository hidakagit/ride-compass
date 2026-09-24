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

#: 書いた後の上書きを読んで検算した結果（`load_tuning_values`の代役が返す）。
LOADED = {"speed.crr": 0.006}


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

    def apply(values):
        recorded.append(("apply_tuning_values", values))

    stub("read_overrides", {"speed.crr": 0.006, "turn.right_seconds": 9.0})
    stub("set_override")
    stub("clear_override")
    stub("load_tuning_values", LOADED)
    monkeypatch.setattr(tuning_service, "apply_tuning_values", bound(tuning_service.apply_tuning_values, apply))
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
async def test_saving_loads_the_values_before_commit_and_only_swaps_them_in_after(events, value, write):
    recorded, _ = events
    session = Session(recorded)

    await tuning_service.save_override(session, "speed.crr", value)

    # 読んで検算するのは確定の前（失敗すれば書き込みごと取り消せる）。確定の後は、その値への
    # 差し替えだけ——DBを読み直さず、DBに無い値がプロセスだけで効くこともない
    assert recorded == [write, ("load_tuning_values",), "commit", ("apply_tuning_values", LOADED)]


@pytest.mark.parametrize(
    ("value", "failing_step"),
    [
        (0.006, "set_override"),
        (None, "clear_override"),
        # 書いた後の上書きの読み出し・検算の失敗（例: 別の行が宣言の範囲の外）も、書き込みごと取り消す
        (0.006, "load_tuning_values"),
        (None, "load_tuning_values"),
        (0.006, "commit"),
    ],
)
async def test_a_failed_save_is_rolled_back_raised_and_not_applied(events, value, failing_step):
    recorded, failing = events
    session = Session(recorded, fail_on_commit=failing_step == "commit")
    failing.add(failing_step)

    with pytest.raises(RuntimeError):
        await tuning_service.save_override(session, "speed.crr", value)

    # 半分だけ書けた状態を反映すると、DBと動いている値が食い違う
    assert recorded[-1] == "rollback"
    assert "commit" not in recorded
    assert ("apply_tuning_values", LOADED) not in recorded
