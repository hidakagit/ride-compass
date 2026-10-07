"""`scripts/axis_apply.py`——軸の定義1本を、本番の今の定義との差を見てから管理APIで入れる道具。

入口は`run(parse_args(引数), client)`で、見るのは画面に出す文・終了コードと、本番の管理APIへ何を書いたか。

ここで見ないもの:
- 宛先と認証情報をファイルから読んで`run`へ渡す結線（`main`） → 見ない（読み取りは`_prod_env.py`の持ち物）
- 管理APIそのもののガード（公開済みの軸を拒む等） → `test_axis_admin_routes.py`・`test_axis_registry_service.py`
- 読めないファイルで本番の今の定義を読みに行かないこと——読む軸の id がファイルから来るので、読めないうちは読みに行けない
  （構造が守る）。壊れた JSON は、定義として読めない JSON と同じ断り（`load_definition`の1つの except）の同じ側

**本番の管理APIと軸カタログは代役にする**（網の境界）。代役は、公開済みの軸の更新・削除を409で拒み、
単体取得の応答に算出項目を足し、軸カタログは公開の軸だけを、体感ラベルを地図の段へ引き直した`map_paint`へ移して返す——道具が前提にする管理APIの約束だけを持つ。
"""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import axis_apply  # noqa: E402

ADMIN = "/api/admin/axis-definitions"


def definition(**fields) -> dict:
    return {
        "axis_id": "axis_a",
        "label": "軸",
        "default_weight": 1.0,
        "shape": {"kind": "breakpoint_linear", "terms": [{"material": "m"}], "breakpoints": [[0.0, 0.0], [1.0, 100.0]]},
        **fields,
    }


class AdminApi:
    """本番の管理APIと軸カタログの代役。書いた操作（GET以外）を順に`writes`へ残す。"""

    def __init__(self, *axes: dict) -> None:
        self.axes = {a["axis_id"]: dict(a) for a in axes}
        self.writes: list[tuple[str, str]] = []
        self.failures: list[dict] = []
        self.catalog_overrides: dict[str, dict] = {}
        self.catalog_listing: dict[str, bool] = {}
        self.stored_as = lambda body: body

    def fail(self, method: str, path: str, status: int = 422, body: object = None, *, after: bool = False) -> None:
        """次に`method path`が来たら1回だけ`status`で断る。`after`なら書いてから断る（書いた後の応答が届かない）。"""
        self.failures.append({"method": method, "path": path, "status": status, "body": body, "after": after})

    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        if method != "GET":
            self.writes.append((method, path))
        failure = next((f for f in self.failures if (f["method"], f["path"]) == (method, path)), None)
        if failure is not None:
            self.failures.remove(failure)
            if failure["after"]:
                self._serve(method, path, request)
            body = failure["body"]
            return httpx.Response(failure["status"], **({"text": body} if isinstance(body, str) else {"json": body}))
        return self._serve(method, path, request)

    def _serve(self, method: str, path: str, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        axis_id = path.removeprefix(ADMIN + "/").removesuffix("/unpublish")
        current = self.axes.get(axis_id)
        if path == "/api/axis-catalog":
            return httpx.Response(200, json={"axes": [self._catalog_entry(a) for a in self.axes.values() if self._listed(a)]})
        if method == "POST" and path == ADMIN:
            self.axes[body["axis_id"]] = self.stored_as(body)
            return httpx.Response(201, json=body)
        if current is None:
            return httpx.Response(404, json={"detail": "Not Found"})
        if method == "GET":
            return httpx.Response(200, json={**current, "display": {"kind": "none"}, "weight_share_when_published": 0.5})
        if path.endswith("/unpublish"):
            current["is_published"] = False
            return httpx.Response(200, json=current)
        if current.get("is_published"):
            return httpx.Response(409, json={"detail": "公開中の軸です"})
        if method == "PUT":
            self.axes[axis_id] = self.stored_as(body)
            return httpx.Response(200, json=body)
        del self.axes[axis_id]
        return httpx.Response(204)

    def _listed(self, axis: dict) -> bool:
        return self.catalog_listing.get(axis["axis_id"], bool(axis.get("is_published")))

    def _catalog_entry(self, axis: dict) -> dict:
        labels = axis.get("display_band_labels_override")
        entry = {key: value for key, value in axis.items() if key != "display_band_labels_override"}
        paint = {"band_labels": None if labels is None else labels[:1]}
        return {**entry, "map_paint": paint, "raw_value_units": {"unit": None}, **self.catalog_overrides.get(axis["axis_id"], {})}


@pytest.fixture
def run(tmp_path, capsys):
    def run(api: AdminApi, *argv: str, desired: dict | None = None) -> tuple[int, str, str]:
        args = list(argv)
        if desired is not None:
            path = tmp_path / "axis.json"
            path.write_text(json.dumps(desired, ensure_ascii=False), encoding="utf-8")
            args.insert(0, str(path))
        with httpx.Client(transport=httpx.MockTransport(api.handle), base_url="http://backend") as client:
            code = axis_apply.run(axis_apply.parse_args(args), client)
        out, err = capsys.readouterr()
        return code, out, err

    return run


def fingerprint(out: str) -> str:
    return next(line.removeprefix("指紋: ") for line in out.splitlines() if line.startswith("指紋: "))


def apply(run, api: AdminApi, *argv: str, desired: dict | None = None) -> tuple[int, str, str]:
    """差を出して、そのとき出た指紋で書く（使う人の手順どおり）。"""
    _, out, _ = run(api, *argv, desired=desired)
    return run(api, *argv, "--apply", fingerprint(out), desired=desired)


class TestShowingTheChange:
    def test_a_dry_run_shows_the_change_and_how_to_write_it_and_writes_nothing(self, run):
        api = AdminApi(definition())

        code, out, _ = run(api, desired=definition(default_weight=2.0))

        assert code == 0
        assert "軸 axis_a: 下書き → 下書き" in out
        assert "書く操作: 定義を書き換える" in out
        assert f"--apply {fingerprint(out)}" in out
        assert api.writes == []

    def test_a_nested_change_is_shown_leaf_by_leaf_grouped_by_field_with_vanishing_leaves_first(self, run):
        api = AdminApi(definition())
        desired = definition(shape={"kind": "categorical", "material": "c", "mapping": {"x": 10.0}}, label="新しい名前")

        _, out, _ = run(api, desired=desired)

        assert [line.strip() for line in out.splitlines() if line.startswith("  ")] == [
            'shape.kind: "breakpoint_linear" → "categorical"',
            'shape.terms: [{"material": "m", "weight": 1.0, "required": true}] → （なし）',
            'shape.preprocess: "identity" → （なし）',
            "shape.breakpoints: [[0.0, 0.0], [1.0, 100.0]] → （なし）",
            'shape.material: （なし） → "c"',
            "shape.mapping.x: （なし） → 10.0",
            'label: "軸" → "新しい名前"',
        ]

    def test_the_same_definition_needs_no_writing(self, run):
        api = AdminApi(definition())

        code, out, _ = run(api, desired=definition())

        assert code == 0
        assert "差はありません" in out
        assert api.writes == []

    def test_a_file_that_is_not_a_definition_is_refused_without_writing(self, run, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text(json.dumps({"axis_id": "axis_a"}), encoding="utf-8")
        api = AdminApi()

        code, _, err = run(api, str(path))

        assert code == 1
        assert "軸の定義として読めません" in err
        assert api.writes == []


class TestWriting:
    @pytest.mark.parametrize(
        ("current", "writes"),
        [
            (None, [("POST", ADMIN)]),
            (definition(), [("PUT", f"{ADMIN}/axis_a")]),
            (definition(is_published=True), [("POST", f"{ADMIN}/axis_a/unpublish"), ("PUT", f"{ADMIN}/axis_a")]),
        ],
    )
    def test_the_operations_follow_the_current_state(self, run, current, writes):
        api = AdminApi(*([current] if current else []))
        desired = definition(default_weight=2.0, is_published=True, display_thresholds_override=[0.5], display_band_labels_override=["弱", "強"])

        code, out, _ = apply(run, api, desired=desired)

        assert code == 0
        assert "書きました" in out
        assert api.writes == writes
        assert api.axes["axis_a"]["default_weight"] == 2.0
        assert api.axes["axis_a"]["is_published"] is True

    @pytest.mark.parametrize(
        ("current", "writes"),
        [
            (definition(), [("DELETE", f"{ADMIN}/axis_a")]),
            (definition(is_published=True), [("POST", f"{ADMIN}/axis_a/unpublish"), ("DELETE", f"{ADMIN}/axis_a")]),
        ],
    )
    def test_deleting_unpublishes_a_published_axis_first(self, run, current, writes):
        api = AdminApi(current)

        code, out, _ = apply(run, api, "--delete", "axis_a")

        assert code == 0
        assert "軸 axis_a: " in out and " → 削除" in out
        assert api.writes == writes
        assert api.axes == {}

    def test_deleting_an_axis_production_lacks_is_refused(self, run):
        code, _, err = run(AdminApi(), "--delete", "axis_a")

        assert code == 1
        assert "本番にありません" in err

    def test_nothing_is_written_when_production_changed_after_the_change_was_shown(self, run):
        api = AdminApi(definition())
        desired = definition(default_weight=2.0)
        _, out, _ = run(api, desired=desired)
        api.axes["axis_a"]["label"] = "別の人が変えた"

        code, _, err = run(api, "--apply", fingerprint(out), desired=desired)

        assert code == 1
        assert "指紋が一致しません" in err
        assert api.writes == []


class TestFailures:
    @pytest.mark.parametrize(("body", "shown"), [({"detail": "材料が足りません"}, "材料が足りません"), ("壊れた応答", "壊れた応答")])
    def test_a_refused_write_reports_what_production_said(self, run, body, shown):
        api = AdminApi(definition())
        api.fail("PUT", f"{ADMIN}/axis_a", body=body)

        code, _, err = apply(run, api, desired=definition(default_weight=2.0))

        assert code == 1
        assert f"PUT {ADMIN}/axis_a が422を返しました: {shown}" in err

    def test_a_refused_unpublishing_changed_nothing_and_is_not_put_back(self, run):
        api = AdminApi(definition(is_published=True))
        api.fail("POST", f"{ADMIN}/axis_a/unpublish", status=500, body={"detail": "取り消せません"})

        code, _, err = apply(run, api, desired=definition(default_weight=2.0, is_published=True))

        assert code == 1
        assert "取り消せません" in err
        assert api.writes == [("POST", f"{ADMIN}/axis_a/unpublish")]

    @pytest.mark.parametrize(
        ("failing", "argv"),
        [
            ({"method": "PUT", "after": False}, ()),
            ({"method": "DELETE", "after": True}, ("--delete", "axis_a")),
            ({"method": "PUT", "after": True}, ()),
        ],
        ids=["left-unpublished", "gone", "written-and-published"],
    )
    def test_a_failure_after_unpublishing_puts_the_published_original_back(self, run, failing, argv):
        api = AdminApi(definition(is_published=True))
        api.fail(failing["method"], f"{ADMIN}/axis_a", status=500, after=failing["after"])

        code, _, err = apply(run, api, *argv, desired=None if argv else definition(default_weight=2.0, is_published=True))

        assert code == 1
        assert "元の定義（公開）へ戻しました" in err
        assert api.axes["axis_a"]["is_published"] is True
        assert api.axes["axis_a"]["default_weight"] == 1.0

    def test_when_the_original_cannot_be_put_back_it_is_shown_for_restoring_by_hand(self, run):
        api = AdminApi(definition(is_published=True))
        api.fail("PUT", f"{ADMIN}/axis_a")
        api.fail("PUT", f"{ADMIN}/axis_a")

        code, _, err = apply(run, api, desired=definition(default_weight=2.0, is_published=True))

        assert code == 1
        assert "手で戻してください" in err
        assert '"default_weight": 1.0' in err

    def test_an_unreachable_production_is_reported(self, run):
        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("接続できません", request=request)

        api = AdminApi()
        api.handle = unreachable

        code, _, err = run(api, desired=definition())

        assert code == 1
        assert f"GET {ADMIN}/axis_a が届きませんでした" in err


class TestVerifying:
    def test_a_definition_production_did_not_keep_as_written_is_reported(self, run):
        api = AdminApi(definition())
        api.stored_as = lambda body: {**body, "label": "書き換わった"}

        code, _, err = apply(run, api, desired=definition(default_weight=2.0))

        assert code == 1
        assert "書いた定義と一致しません" in err
        assert '  label: "軸" → "書き換わった"' in err

    def test_a_published_axis_the_catalog_serves_differently_is_reported(self, run):
        api = AdminApi()
        api.catalog_overrides["axis_a"] = {"label": "古い名前"}

        code, _, err = apply(run, api, desired=definition(is_published=True))

        assert code == 1
        assert "['label']" in err

    @pytest.mark.parametrize(
        ("desired", "listed", "shown"),
        [(definition(is_published=True), False, "ありません"), (definition(), True, "残っています")],
    )
    def test_the_catalog_must_list_an_axis_exactly_when_it_is_published(self, run, desired, listed, shown):
        api = AdminApi()
        api.catalog_listing["axis_a"] = listed

        code, _, err = apply(run, api, desired=desired)

        assert code == 1
        assert f"軸カタログに軸 axis_a が{shown}" in err
