"""`scripts/axis_apply.py`——軸の定義1本を、差を見てから管理APIで入れる道具。

管理APIは網の境界で差し替える（`httpx.MockTransport`の上の代役）。代役が真似るのは道具の操作の順を決める
性質だけ: 公開済みの軸は更新も削除も拒む、取り消しは公開の印だけを外す、軸カタログは公開済みの軸だけを返す。
"""

import json
import re
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import axis_apply  # noqa: E402
from app.domain.axis_definitions import AxisDefinition  # noqa: E402

ADMIN = axis_apply.ADMIN_PATH


def definition(axis_id="a", **fields):
    body = {
        "axis_id": axis_id,
        "label": "軸A",
        "default_weight": 1.0,
        "is_published": True,
        "shape": {"kind": "categorical", "material": "mat_old", "mapping": {"good": 0.0, "bad": 80.0}},
    }
    body.update(fields)
    return AxisDefinition.model_validate(body).model_dump(mode="json")


class FakeAdminApi:
    def __init__(self, *axes):
        self.axes = {axis["axis_id"]: axis for axis in axes}
        self.writes: list[tuple[str, str]] = []
        #: (method, path) → 返す状態コード。`once`に入れたものは1回だけ失敗する。
        self.fail: dict[tuple[str, str], int] = {}
        self.once: set[tuple[str, str]] = set()
        self.frozen_catalog: list[dict] | None = None

    def catalog(self) -> list[dict]:
        hidden = {"is_published", "priority_overrides", "time_scope"}
        return [
            {**{k: v for k, v in axis.items() if k not in hidden}, "display": {"kind": "none"}}
            for axis in self.axes.values()
            if axis["is_published"]
        ]

    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        if method != "GET":
            self.writes.append((method, path))
        if (method, path) in self.fail:
            status = self.fail[(method, path)]
            if (method, path) in self.once:
                del self.fail[(method, path)]
            return httpx.Response(status, json={"detail": "代役が拒否"})
        if path == axis_apply.CATALOG_PATH:
            return httpx.Response(200, json={"axes": self.frozen_catalog if self.frozen_catalog is not None else self.catalog()})
        rest = path.removeprefix(ADMIN).strip("/")
        axis_id, _, action = rest.partition("/")
        stored = self.axes.get(axis_id)
        if method == "POST" and not rest:
            body = json.loads(request.content)
            self.axes[body["axis_id"]] = body
            return httpx.Response(201, json=body)
        if stored is None:
            return httpx.Response(404, json={"detail": "見つかりません"})
        if method == "GET":
            return httpx.Response(200, json={**stored, "display": {"kind": "none"}, "weight_share_when_published": 0.5})
        if action == "unpublish":
            self.axes[axis_id] = {**stored, "is_published": False}
            return httpx.Response(200, json=self.axes[axis_id])
        if stored["is_published"]:
            return httpx.Response(409, json={"detail": "公開済みの軸は変えられません"})
        if method == "PUT":
            self.axes[axis_id] = json.loads(request.content)
            return httpx.Response(200, json=self.axes[axis_id])
        del self.axes[axis_id]
        return httpx.Response(204)


def run(api: FakeAdminApi, *argv: str) -> int:
    client = httpx.Client(base_url="https://backend.test", transport=httpx.MockTransport(api.handle))
    with client:
        return axis_apply.run(axis_apply.parse_args(list(argv)), client)


def change_file(tmp_path: Path, body: dict) -> str:
    path = tmp_path / "change.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8", newline="\n")
    return str(path)


def dry_run(api: FakeAdminApi, capsys, *argv: str) -> tuple[str, str]:
    """差の表示（書かない）を通し、出力と指紋を返す。"""
    assert run(api, *argv) == 0
    out = capsys.readouterr().out
    match = re.search(r"指紋: (\w+)", out)
    assert match
    return out, match.group(1)


def dry_run_mark(api: FakeAdminApi, capsys, *argv: str) -> str:
    return dry_run(api, capsys, *argv)[1]


NEW_SHAPE = {"kind": "categorical", "material": "mat_new", "mapping": {"good": 0.0, "bad": 100.0, "unknown": 40.0}}


def test_dry_run_shows_each_changed_leaf_before_and_after_and_writes_nothing(tmp_path, capsys):
    api = FakeAdminApi(definition())
    file = change_file(tmp_path, definition(shape=NEW_SHAPE))

    assert run(api, file) == 0

    out = capsys.readouterr().out
    assert (
        '  shape.material: "mat_old" → "mat_new"\n'
        "  shape.mapping.bad: 80.0 → 100.0\n"
        "  shape.mapping.unknown: （なし） → 40.0\n"
    ) in out
    assert "shape.mapping.good" not in out
    assert "書く操作: 公開を取り消す → 定義を書き換える（公開にする）" in out
    assert api.writes == []


def test_apply_with_the_dry_run_mark_rewrites_a_published_axis_and_confirms_it_in_the_catalog(tmp_path, capsys):
    desired = definition(shape=NEW_SHAPE)
    api = FakeAdminApi(definition())
    file = change_file(tmp_path, desired)
    mark = dry_run_mark(api, capsys, file)

    assert run(api, file, "--apply", mark) == 0

    assert api.writes == [("POST", f"{ADMIN}/a/unpublish"), ("PUT", f"{ADMIN}/a")]
    assert api.axes["a"] == desired
    assert "反映を確かめました" in capsys.readouterr().out


def test_apply_writes_nothing_when_production_changed_after_the_dry_run(tmp_path, capsys):
    api = FakeAdminApi(definition())
    file = change_file(tmp_path, definition(shape=NEW_SHAPE))
    mark = dry_run_mark(api, capsys, file)
    api.axes["a"] = definition(label="別の人が変えた")

    assert run(api, file, "--apply", mark) == 1

    assert api.writes == []
    assert "指紋が一致しません" in capsys.readouterr().err


def test_failure_after_unpublishing_puts_the_original_definition_back_on_public(tmp_path, capsys):
    original = definition()
    api = FakeAdminApi(original)
    file = change_file(tmp_path, definition(shape=NEW_SHAPE))
    mark = dry_run_mark(api, capsys, file)
    api.fail[("PUT", f"{ADMIN}/a")] = 422
    api.once.add(("PUT", f"{ADMIN}/a"))

    assert run(api, file, "--apply", mark) == 1

    assert api.axes["a"] == original
    err = capsys.readouterr().err
    assert "422" in err and "元の定義（公開）へ戻しました" in err


def test_when_the_original_cannot_be_put_back_it_prints_the_original_for_a_manual_restore(tmp_path, capsys):
    original = definition()
    api = FakeAdminApi(original)
    file = change_file(tmp_path, definition(shape=NEW_SHAPE))
    mark = dry_run_mark(api, capsys, file)
    api.fail[("PUT", f"{ADMIN}/a")] = 503

    assert run(api, file, "--apply", mark) == 1

    err = capsys.readouterr().err
    assert "元の定義へ戻せませんでした" in err
    assert json.dumps(original, ensure_ascii=False, indent=2) in err


def test_a_draft_is_updated_with_one_write_and_a_missing_axis_is_added(tmp_path, capsys):
    desired = definition(shape=NEW_SHAPE)
    api = FakeAdminApi(definition(is_published=False), definition("b"))
    file = change_file(tmp_path, desired)
    assert run(api, file, "--apply", dry_run_mark(api, capsys, file)) == 0

    new_axis = definition("c", is_published=False)
    new_file = change_file(tmp_path, new_axis)
    out, mark = dry_run(api, capsys, new_file)
    assert run(api, new_file, "--apply", mark) == 0

    assert 'label: （なし） → "軸A"' in out and "\n  : " not in out
    assert api.writes == [("PUT", f"{ADMIN}/a"), ("POST", ADMIN)]
    assert api.axes["a"] == desired and api.axes["c"] == new_axis


def test_delete_unpublishes_a_published_axis_first(capsys):
    api = FakeAdminApi(definition(), definition("b"))

    assert run(api, "--delete", "a", "--apply", dry_run_mark(api, capsys, "--delete", "a")) == 0

    assert api.writes == [("POST", f"{ADMIN}/a/unpublish"), ("DELETE", f"{ADMIN}/a")]
    assert "a" not in api.axes


def test_no_difference_means_no_mark_and_no_writes(tmp_path, capsys):
    api = FakeAdminApi(definition())

    assert run(api, change_file(tmp_path, definition())) == 0

    out = capsys.readouterr().out
    assert "差はありません" in out and "指紋" not in out
    assert api.writes == []


def test_a_catalog_that_does_not_reflect_the_write_fails_the_run(tmp_path, capsys):
    api = FakeAdminApi(definition())
    api.frozen_catalog = api.catalog()
    file = change_file(tmp_path, definition(shape=NEW_SHAPE))
    mark = dry_run_mark(api, capsys, file)

    assert run(api, file, "--apply", mark) == 1

    assert "軸カタログの軸 a の ['shape'] が書いた定義と一致しません" in capsys.readouterr().err


@pytest.mark.parametrize("body", ["{", json.dumps({"axis_id": "a", "label": "軸A", "unknown_field": 1})])
def test_a_file_that_is_not_an_axis_definition_stops_before_reading_production(tmp_path, capsys, body):
    path = tmp_path / "change.json"
    path.write_text(body, encoding="utf-8", newline="\n")
    api = FakeAdminApi(definition())

    assert run(api, str(path)) == 1

    assert "軸の定義として読めません" in capsys.readouterr().err
