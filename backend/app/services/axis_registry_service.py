"""評価軸レジストリの起動時ロード＋管理API書き込み直後の反映。

`AXIS_DEFINITIONS`は評価ホットパスから同期的に読まれる。DBを正本にしつつその同期アクセスを
変えずに済ませるため、**モジュールレベルの同じdictオブジェクトをin-placeで書き換える**。
辞書自体を再代入すると`from ... import AXIS_DEFINITIONS`で束縛済みの参照先が古いままになる
ため、必ず`replace_axis_definitions`で中身だけを差し替えること（別スレッドの読みとの排他もそこが持つ）。

反映はプロセス単位で、他プロセスでの編集はこのプロセスへ届かない（単一プロセスデプロイが
前提）。
"""

import logging
from collections.abc import Mapping

from app.domain.axis_definitions import (
    AxisDefinition,
    AxisDependencyCycleError,
    AxisMaterialConflictError,
    check_axis_definition,
    check_axis_set,
    check_internal_axis_not_published,
    check_publish_immutability,
    named_references,
    replace_axis_definitions,
)
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

logger = logging.getLogger("ridecompass.axis_registry")


class AxisDefinitionSyncError(RuntimeError):
    """軸定義DBが期待する状態でない場合に送出する。

    コード内蔵の既定値へフォールバックしない。起動時の呼び出し元はこれを捕捉せず、
    アプリの起動自体を失敗させる——検知が起動ログの目視に依存すると、不整合を抱えたまま
    動き続ける。
    """


def _rejected_axes(definitions: dict[str, AxisDefinition]) -> dict[str, str]:
    """軸id→値の不変条件（`check_axis_definition`）に通らない理由。

    行をモデルへ組み立てる検証は軸そのものしか見ないため、削除済みの材料idを参照し続けている行等は
    「読めるが意味的には古い」状態のまま素通りする。管理APIを通らずに書かれた行（復元）も、ここで
    管理APIと同じ検査を通る。軸の参照は同じ読み込み結果の軸だけを受け入れる。
    """
    rejected: dict[str, str] = {}
    for axis_id, definition in definitions.items():
        try:
            check_axis_definition(definition, definitions)
        except ValueError as error:
            rejected[axis_id] = str(error)
    return rejected


def _loading_problem(definitions: dict[str, AxisDefinition]) -> str | None:
    """起動時の読み込みがこの軸の集合を受け入れない理由。受け入れるならNone。運用者が読む文で、軸はidで名指す。

    管理APIの書き込みも確定する前の状態を同じ判定（0行と`_rejected_axes`と`check_axis_set`）へ通すが、断りの文は
    画面に出るため書き込みの側で書く（`_check_loadable_after_write`・`AxisRegistryAdminService.delete`）。
    """
    if not definitions:
        return (
            "axis_definitionsテーブルが空です（軸の行はスキーマと一緒には作られない。入る経路は管理APIと、"
            "バックアップからの復元 .claude/skills/production-data/SKILL.md「本番DBを失ったとき」）"
        )
    rejected = _rejected_axes(definitions)
    if rejected:
        reasons = "／".join(f"{axis_id}: {reason}" for axis_id, reason in rejected.items())
        return f"アプリが受け入れない軸があります（{reasons}）"
    try:
        check_axis_set(definitions)
    except AxisMaterialConflictError as error:
        materials = ", ".join(sorted(error.overlapping_materials))
        reason = f"{error.axis_id}: 材料 {materials} を {error.conflicting_axis_id} も使っています"
    except AxisDependencyCycleError as error:
        reason = f"組み合わせが輪になっています {'→'.join(error.cycle)}"
    except ValueError as error:  # 軸idと材料idの衝突。文が軸をidで名指している
        reason = str(error)
    else:
        return None
    return f"アプリが受け入れない軸の組み合わせがあります（{reason}）"


async def refresh_axis_definitions(repository: AxisDefinitionRepository) -> None:
    """DBの内容でAXIS_DEFINITIONSをin-place更新する。

    DBが全軸の唯一の正本で、これが唯一のロード経路。Python側に既定値は無い。読めない・0行・
    値の不変条件に通らない軸のいずれも`AxisDefinitionSyncError`で、起動時はそのまま起動失敗になる。
    """
    try:
        definitions = await repository.list_all()
    except Exception as exc:  # noqa: BLE001 fail-fast用に専用の例外へラップして再送出する
        raise AxisDefinitionSyncError(f"軸定義のDB読み込みに失敗しました error={exc!r}") from exc
    problem = _loading_problem(definitions)
    if problem is not None:
        raise AxisDefinitionSyncError(f"軸定義DBを読み込めません: {problem}")
    logger.info("軸定義をDBから読み込みました axes=%d", len(definitions))
    replace_axis_definitions(definitions)


def _check_loadable_after_write(after: dict[str, AxisDefinition], written_axis_id: str) -> None:
    """作成・更新の後の全軸が起動時の読み込みを通るか。軸を足す・差し替える書き込みなので、0行にはならない。

    集合の誤り（`check_axis_set`）は、その文のまま断る。材料の重なりは後に並ぶ軸の誤りとして名指されるので、
    書いた軸を最後に並べて渡す——並び順のまま渡すと、前に並ぶ軸を直したときに、直した軸を「すでに使っている軸」と名指す。
    """
    rejected = _rejected_axes(after)
    if rejected:
        reasons = "／".join(f"{named_references([axis_id], after)}: {reason}" for axis_id, reason in rejected.items())
        raise ValueError(f"この変更を確定すると、次の起動で読み込めない軸ができるため確定しません（{reasons}）")
    others = {axis_id: d for axis_id, d in after.items() if axis_id != written_axis_id}
    check_axis_set({**others, written_axis_id: after[written_axis_id]})


def _check_deletable(axis_id: str, existing: dict[str, AxisDefinition]) -> None:
    """消した後の全軸を起動時の読み込みが受け入れるか。受け入れないのは、最後の1軸を消すときと、
    ほかの軸が組み合わせに使っている軸を消すとき。

    消す前の全軸は読み込みを通っている（起動と書き込みのたびに確かめている）。読み込みの判定のうち軸を減らして
    破れうるのは参照先の実在だけ（集合の判定`check_axis_set`は、軸を減らしても破れない）なので、消した後に
    通らなくなる軸は、消す軸を指している軸である。
    """
    name = named_references([axis_id], existing)
    after = {aid: d for aid, d in existing.items() if aid != axis_id}
    if not after:
        raise ValueError(
            f"{name}は最後の1本の軸なので削除できません（軸が1本も無いとアプリが起動できません）。"
            "先に別の軸を作ってから削除してください。"
        )
    rejected = _rejected_axes(after)
    if rejected:
        users = named_references(rejected, existing)
        raise ValueError(
            f"{name}は{users}が組み合わせに使っているため削除できません。"
            f"先に{users}の組み合わせる軸から{name}を外すか、{users}を削除してください。"
        )


def _definitions_of(existing: Mapping[str, tuple[AxisDefinition, int]]) -> dict[str, AxisDefinition]:
    """`list_all_with_sort_order`の結果から並び順を落とす。"""
    return {axis_id: definition for axis_id, (definition, _) in existing.items()}


class AxisRegistryAdminService:
    """軸定義CRUD管理APIのユースケース層。

    書き込みは1操作=1トランザクションで確定し、直後に`refresh_axis_definitions`で
    プロセス内へ反映する。作成・更新・削除は、確定する前に書いた後の全軸を起動時の読み込みと
    同じ判定（0行と`_rejected_axes`と`check_axis_set`）へ通す。

    書き込む操作はいずれも「読む→Python側で検証する→書く」の形のため、先頭で
    `acquire_write_lock`を取ってその全体を直列化する（取らないとTOCTOUで検証をすり抜ける。
    `axis_definition_repository.py: acquire_write_lock`のdocstring参照）。
    """

    def __init__(self, repository: AxisDefinitionRepository):
        self._repository = repository

    async def list_all(self) -> dict[str, AxisDefinition]:
        return await self._repository.list_all()

    async def _write(self, definition: AxisDefinition, sort_order: int) -> None:
        """1軸を書いて確定し、プロセス内へ反映する。"""
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def create(self, definition: AxisDefinition) -> dict[str, AxisDefinition]:
        """軸を足し、足した後の全軸を返す。"""
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all_with_sort_order()
        if definition.axis_id in existing:
            raise ValueError(f"axis_id={definition.axis_id} は既に存在します")
        existing_definitions = _definitions_of(existing)
        check_internal_axis_not_published(definition, existing_definitions)
        after = {**existing_definitions, definition.axis_id: definition}
        _check_loadable_after_write(after, definition.axis_id)
        sort_order = max((order for _, order in existing.values()), default=-1) + 1
        await self._write(definition, sort_order)
        return after

    async def update(self, axis_id: str, definition: AxisDefinition) -> dict[str, AxisDefinition]:
        """軸を書き換え、書き換えた後の全軸を返す。"""
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        existing_definition, sort_order = existing[axis_id]
        # 公開済みかどうかは**DB側の既存の状態**で判定する。payloadのis_publishedを見ると、
        # 未公開を装って公開済み軸の更新を通す抜け道になる。
        check_publish_immutability(existing_definition, "updated", definition)
        existing_definitions = _definitions_of(existing)
        check_internal_axis_not_published(definition, existing_definitions)
        after = {**existing_definitions, axis_id: definition}
        _check_loadable_after_write(after, axis_id)
        await self._write(definition, sort_order)
        return after

    async def delete(self, axis_id: str) -> None:
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all()
        if axis_id in existing:
            check_publish_immutability(existing[axis_id], "deleted")
            _check_deletable(axis_id, existing)
        # 削除できるのは常に下書き軸だけ（公開済みは上のガードで止まる）で、下書きは
        # `GET /api/axis-catalog`に出ない。そのため「利用者の保存済み設定がこのaxis_idを
        # 重みキーとして参照したまま残る」状況は起こらず、その整合性検査を持たない。
        deleted = await self._repository.delete(axis_id)
        if not deleted:
            raise KeyError(axis_id)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def unpublish(self, axis_id: str) -> dict[str, AxisDefinition]:
        """公開済み軸を下書きへ戻し、戻した後の全軸を返す。`update()`が公開済み軸を一律拒否するための逃げ道。

        **フロント側が公開軸集合の変化に合わせてroutePreferenceのキーを自己修復すること**が
        前提。それが無いと、旧設定を保持したブラウザは次のルート生成で
        RoutePreferenceWeightsのキー一致検証に落ちて422になる。
        """
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        definition, sort_order = existing[axis_id]
        existing_definitions = _definitions_of(existing)
        if not definition.is_published:
            return existing_definitions  # 既に下書きなら何もしない（べき等）
        unpublished = definition.model_copy(update={"is_published": False})
        await self._write(unpublished, sort_order)
        return {**existing_definitions, axis_id: unpublished}
