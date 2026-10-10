r"""軸の定義1本を、本番の今の定義との差を見てから管理APIで入れる。

    python scripts/axis_apply.py <定義.json>                    # 差を出すだけ（書かない）
    python scripts/axis_apply.py <定義.json> --apply <指紋>     # 差を出したときの指紋を渡して書く
    python scripts/axis_apply.py --delete <axis_id> [--apply <指紋>]

定義のJSONは管理APIの単体取得（`GET /api/admin/axis-definitions/{axis_id}`）と同じ項目の軸1本で、
`is_published`が書いた後の公開の状態になる。書く操作は今の状態から決まる: 無ければ追加、下書きなら更新（1回）、
公開済みなら公開の取り消し→更新、削除は（公開済みなら取り消し→）削除。

**書くのは、差を出したときの指紋を`--apply`に渡したときだけ**。指紋は今の定義と書く定義から作るので、
差を見てから書くまでに本番が変わっていれば一致せず、何も書かずに止まる。公開の取り消しの後の段で失敗したら
元の定義へ戻す。書いた後は、管理APIの単体取得と公開の軸カタログの両方で反映を確かめる。

宛先と認証情報は`backend/.env.oracle.local`の`BACKEND_ORIGIN`（本番backendの直接のオリジン）・
`ADMIN_BASIC_AUTH_USERNAME`・`ADMIN_BASIC_AUTH_PASSWORD`から読み、引数には取らず出力にも出さない。
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.axis_definitions import AxisDefinition  # noqa: E402

ADMIN_PATH = "/api/admin/axis-definitions"
CATALOG_PATH = "/api/axis-catalog"
_ABSENT = object()

Definition = dict[str, Any]


class AxisApplyError(Exception):
    """書けなかった・確かめられなかった。文はそのまま利用者へ出す。"""


@dataclass(frozen=True)
class Step:
    method: str
    path: str
    body: Definition | None
    label: str


def _canonical(fields: dict[str, Any]) -> Definition:
    """比べられる形（全項目・既定値込みのJSON）。"""
    return AxisDefinition.model_validate(fields).model_dump(mode="json")


def load_definition(path: Path) -> Definition:
    try:
        return _canonical(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise AxisApplyError(f"{path} を軸の定義として読めません: {error}") from error


def _request(client: httpx.Client, method: str, path: str, body: Definition | None = None) -> httpx.Response:
    try:
        response = client.request(method, path, json=body)
    except httpx.HTTPError as error:
        raise AxisApplyError(f"{method} {path} が届きませんでした: {error}") from error
    if response.is_error and not (method == "GET" and response.status_code == 404):
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise AxisApplyError(f"{method} {path} が{response.status_code}を返しました: {detail}")
    return response


def read_current(client: httpx.Client, axis_id: str) -> Definition | None:
    response = _request(client, "GET", f"{ADMIN_PATH}/{axis_id}")
    if response.status_code == 404:
        return None
    # 応答は定義に算出項目（地図表示・重みの割合）を足したもの。
    body = response.json()
    return _canonical({key: body[key] for key in AxisDefinition.model_fields if key in body})


def plan(axis_id: str, current: Definition | None, desired: Definition | None) -> list[Step]:
    """今の状態から書く定義へ移る操作の順。差が無ければ空。"""
    unpublish = Step("POST", f"{ADMIN_PATH}/{axis_id}/unpublish", None, "公開を取り消す")
    if desired is None:
        if current is None:
            raise AxisApplyError(f"軸 {axis_id} は本番にありません（消すものがありません）")
        delete = Step("DELETE", f"{ADMIN_PATH}/{axis_id}", None, "削除する")
        return [unpublish, delete] if current["is_published"] else [delete]
    if current is None:
        return [Step("POST", ADMIN_PATH, desired, "追加する")]
    if current == desired:
        return []
    update = Step("PUT", f"{ADMIN_PATH}/{axis_id}", desired, "定義を書き換える" + ("（公開にする）" if desired["is_published"] else ""))
    return [unpublish, update] if current["is_published"] else [update]


def fingerprint(current: Definition | None, desired: Definition | None) -> str:
    text = json.dumps([current, desired], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value:
        flat: dict[str, Any] = {}
        for key, child in value.items():
            flat.update(_flatten(child, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    return {prefix: value}


def _show(value: Any) -> str:
    return "（なし）" if value is _ABSENT else json.dumps(value, ensure_ascii=False)


def diff_lines(before: Definition | None, after: Definition | None) -> list[str]:
    """項目ごとの「前 → 後」。入れ子（shape等）は葉の項目まで分け、消える葉を同じ項目の中で足される葉より先に並べる。"""
    old = _flatten(before) if before else {}
    new = _flatten(after) if after else {}
    keys = list(old) + [key for key in new if key not in old]
    top_level = list(dict.fromkeys(key.split(".")[0] for key in keys))
    keys.sort(key=lambda key: top_level.index(key.split(".")[0]))
    return [
        f"  {key}: {_show(old.get(key, _ABSENT))} → {_show(new.get(key, _ABSENT))}"
        for key in keys
        if old.get(key, _ABSENT) != new.get(key, _ABSENT)
    ]


def _state(definition: Definition | None) -> str:
    if definition is None:
        return "無し"
    return "公開" if definition["is_published"] else "下書き"


def _restore(client: httpx.Client, original: Definition) -> None:
    """元の定義へ戻す。戻せなければ、手で戻すための定義を添えて止まる。"""
    axis_id = original["axis_id"]
    try:
        now = read_current(client, axis_id)
        if now == original:
            return
        if now is None:
            _request(client, "POST", ADMIN_PATH, original)
            return
        if now["is_published"]:
            _request(client, "POST", f"{ADMIN_PATH}/{axis_id}/unpublish")
        _request(client, "PUT", f"{ADMIN_PATH}/{axis_id}", original)
    except AxisApplyError as error:
        raise AxisApplyError(
            f"元の定義へ戻せませんでした（{error}）。本番の軸 {axis_id} を次の定義へ手で戻してください:\n"
            + json.dumps(original, ensure_ascii=False, indent=2)
        ) from error


def execute(client: httpx.Client, current: Definition | None, steps: Sequence[Step]) -> None:
    done = 0
    try:
        for step in steps:
            _request(client, step.method, step.path, step.body)
            done += 1
    except AxisApplyError as error:
        if current is not None and current["is_published"] and done:
            _restore(client, current)
            raise AxisApplyError(f"{error}\n元の定義（公開）へ戻しました。") from error
        raise


def verify(client: httpx.Client, axis_id: str, desired: Definition | None) -> None:
    """管理APIの単体取得と、公開の軸カタログ（利用者の画面が読むもの）の両方で反映を確かめる。"""
    now = read_current(client, axis_id)
    if now != desired:
        raise AxisApplyError("書いた後の定義が、書いた定義と一致しません:\n" + "\n".join(diff_lines(desired, now)))
    axes = _request(client, "GET", CATALOG_PATH).json()["axes"]
    entry = next((axis for axis in axes if axis["axis_id"] == axis_id), None)
    published = desired is not None and desired["is_published"]
    if published != (entry is not None):
        raise AxisApplyError(f"軸カタログに軸 {axis_id} が{'ありません' if published else '残っています'}")
    if entry is not None and desired is not None:
        stale = sorted(key for key in entry if key in desired and entry[key] != desired[key])
        if stale:
            raise AxisApplyError(f"軸カタログの軸 {axis_id} の {stale} が書いた定義と一致しません")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="軸の定義1本を、差を見てから本番の管理APIで入れる")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("file", nargs="?", type=Path, help="軸1本の定義のJSON")
    target.add_argument("--delete", metavar="AXIS_ID", help="この軸を消す")
    parser.add_argument("--apply", metavar="指紋", help="差を出したときの指紋。一致したときだけ書く")
    return parser.parse_args(argv)


def run(args: argparse.Namespace, client: httpx.Client) -> int:
    try:
        desired: Definition | None
        if args.delete:
            desired, axis_id = None, args.delete
        else:
            desired = load_definition(args.file)
            axis_id = desired["axis_id"]
        current = read_current(client, axis_id)
        steps = plan(axis_id, current, desired)
        after = "削除" if desired is None else _state(desired)
        print(f"軸 {axis_id}: {_state(current)} → {after}")
        if not steps:
            print("差はありません。書くものはありません。")
            return 0
        print("\n".join(diff_lines(current, desired)))
        print("書く操作: " + " → ".join(step.label for step in steps))
        mark = fingerprint(current, desired)
        if args.apply is None:
            target = f"--delete {axis_id}" if desired is None else str(args.file)
            print(f"指紋: {mark}")
            print(f"書くには: python scripts/axis_apply.py {target} --apply {mark}")
            return 0
        if args.apply != mark:
            raise AxisApplyError(
                f"指紋が一致しません（渡した {args.apply}、今の本番から作ると {mark}）。"
                "差を見てから本番が変わったか、別の差の指紋です。何も書いていません。差を出し直してください"
            )
        execute(client, current, steps)
        verify(client, axis_id, desired)
    except AxisApplyError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("書きました。管理APIと軸カタログで反映を確かめました。")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    from _prod_env import read_prod_env

    args = parse_args(argv)
    auth = httpx.BasicAuth(read_prod_env("ADMIN_BASIC_AUTH_USERNAME"), read_prod_env("ADMIN_BASIC_AUTH_PASSWORD"))
    with httpx.Client(base_url=read_prod_env("BACKEND_ORIGIN").rstrip("/"), auth=auth, timeout=30.0) as client:
        return run(args, client)


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
