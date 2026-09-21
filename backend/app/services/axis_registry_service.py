"""評価軸レジストリの起動時ロード＋管理API書き込み直後の反映。

`AXIS_DEFINITIONS`は評価ホットパスから同期的に読まれる。DBを正本にしつつその同期アクセスを
変えずに済ませるため、**モジュールレベルの同じdictオブジェクトをin-placeで書き換える**。
辞書自体を再代入すると`from ... import AXIS_DEFINITIONS`で束縛済みの参照先が古いままになる
ため、必ず`.clear()`+`.update()`で中身だけを差し替えること。

反映はプロセス単位で、他プロセスでの編集はこのプロセスへ届かない（単一プロセスデプロイが
前提）。
"""

import logging

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    check_internal_axis_not_published,
    check_material_exclusivity,
    check_publish_immutability,
    topological_axis_order,
)
from app.domain.material_catalog import is_known_material
from app.infrastructure import tile_score_matrix_cache
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

logger = logging.getLogger("ridecompass.axis_registry")


class AxisDefinitionSyncError(RuntimeError):
    """軸定義DBが期待する状態でない場合に送出する。

    コード内蔵の既定値へフォールバックしない。起動時の呼び出し元はこれを捕捉せず、
    アプリの起動自体を失敗させる——検知が起動ログの目視に依存すると、不整合を抱えたまま
    動き続ける。
    """


def _find_unknown_references(definitions: dict[str, AxisDefinition]) -> dict[str, list[str]]:
    """軸id→そのshapeが参照する未知の材料id・軸id。

    Pydanticのバリデーションはshapeの**構造**だけを見て材料の実在を見ないため、削除済みの
    材料idを参照し続けている行は「読めるが意味的には古い」状態のまま素通りする。
    """
    known_axis_ids = set(definitions)
    unknown: dict[str, list[str]] = {}
    for axis_id, definition in definitions.items():
        missing = sorted({m for m in definition.materials if not is_known_material(m) and m not in known_axis_ids})
        if missing:
            unknown[axis_id] = missing
    return unknown


async def refresh_axis_definitions(repository: AxisDefinitionRepository) -> None:
    """DBの内容でAXIS_DEFINITIONSをin-place更新する。

    DBが全軸の唯一の正本で、これが唯一のロード経路。Python側に既定値は無い。読めない・
    0行・未知参照のいずれも`AxisDefinitionSyncError`で、起動時はそのまま起動失敗になる。
    """
    try:
        definitions = await repository.list_all()
    except Exception as exc:  # noqa: BLE001 fail-fast用に専用の例外へラップして再送出する
        raise AxisDefinitionSyncError(f"軸定義のDB読み込みに失敗しました error={exc!r}") from exc
    if not definitions:
        raise AxisDefinitionSyncError(
            "axis_definitionsテーブルが空です（migration未適用の可能性）"
        )
    unknown_references = _find_unknown_references(definitions)
    if unknown_references:
        raise AxisDefinitionSyncError(
            f"軸定義DBに未知の材料/軸参照を検出しました unknown={unknown_references}"
        )
    logger.info("軸定義をDBから読み込みました axes=%d", len(definitions))
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(definitions)
    # スコア行列のキーはタイル座標だけで、軸定義が変わると古いスコアと見分けられない。
    # 無条件に消さずrevisionで判定するのは、この関数が起動時にも必ず1回呼ばれるため
    # ——消すとデプロイのたびにディスク上のスコア行列を丸ごと作り直すことになる。
    # 材料そのもの（graph_material_cache）は温存し、軸編集直後の最初のリクエストが
    # DBへ問い合わせ直さずに済むようにする。
    revision = await repository.get_revision()
    tile_score_matrix_cache.sync_disk_cache_with_axis_revision(revision)


class AxisRegistryAdminService:
    """軸定義CRUD管理APIのユースケース層。

    書き込みは1操作=1トランザクションで確定し、直後に`refresh_axis_definitions`で
    プロセス内へ反映する。

    書き込む操作はいずれも「読む→Python側で検証する→書く」の形のため、先頭で
    `acquire_write_lock`を取ってその全体を直列化する（取らないとTOCTOUで検証をすり抜ける。
    `axis_definition_repository.py: acquire_write_lock`のdocstring参照）。
    """

    def __init__(self, repository: AxisDefinitionRepository):
        self._repository = repository

    async def list_all(self) -> dict[str, AxisDefinition]:
        return await self._repository.list_all()

    async def get(self, axis_id: str) -> AxisDefinition | None:
        existing = await self._repository.get(axis_id)
        return existing[0] if existing else None

    async def create(self, definition: AxisDefinition) -> None:
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all_with_sort_order()
        if definition.axis_id in existing:
            raise ValueError(f"axis_id={definition.axis_id} は既に存在します")
        # 軸の評価結果は材料と同じ辞書へ書き戻されるため、axis_idが材料idと衝突すると
        # 同名の生材料値を黙って上書きし、それ以降に評価される軸が壊れる。axis_idは
        # updateで変えられないため、この検査はcreate時だけでよい。
        if is_known_material(definition.axis_id):
            raise ValueError(f"axis_id={definition.axis_id} は既存の材料idと衝突しています")
        # 新規軸が既存軸の材料を黙って再利用し、二重計上が混入するのを防ぐ。
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        check_internal_axis_not_published(definition, existing_definitions)
        # 軸間参照（内部軸→公開軸）の循環検証。参照先axis_idの実在はrouter層が既に
        # 確かめている前提。
        topological_axis_order({**existing_definitions, definition.axis_id: definition})
        sort_order = max((order for _, order in existing.values()), default=-1) + 1
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def update(self, axis_id: str, definition: AxisDefinition) -> None:
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        existing_definition, sort_order = existing[axis_id]
        # 公開済みかどうかは**DB側の既存の状態**で判定する。payloadのis_publishedを見ると、
        # 未公開を装って公開済み軸の更新を通す抜け道になる。
        check_publish_immutability(existing_definition, "updated", definition)
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        check_internal_axis_not_published(definition, existing_definitions)
        topological_axis_order({**existing_definitions, axis_id: definition})
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def delete(self, axis_id: str) -> None:
        await self._repository.acquire_write_lock()
        # 空にすると、直後の`refresh_axis_definitions`が0行を検知して起動・反映に失敗する。
        existing = await self._repository.list_all()
        if axis_id in existing and len(existing) == 1:
            raise ValueError("最後の1軸は削除できません")
        if axis_id in existing:
            check_publish_immutability(existing[axis_id], "deleted")
        # 削除できるのは常に下書き軸だけ（公開済みは上のガードで止まる）で、下書きは
        # `GET /api/axis-catalog`に出ない。そのため「利用者の保存済み設定がこのaxis_idを
        # 重みキーとして参照したまま残る」状況は起こらず、その整合性検査を持たない。
        deleted = await self._repository.delete(axis_id)
        if not deleted:
            raise KeyError(axis_id)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def unpublish(self, axis_id: str) -> None:
        """公開済み軸を下書きへ戻す。`update()`が公開済み軸を一律拒否するための逃げ道。

        **フロント側が公開軸集合の変化に合わせてroutePreferenceのキーを自己修復すること**が
        前提。それが無いと、旧設定を保持したブラウザは次のルート生成で
        RoutePreferenceWeightsのキー一致検証に落ちて422になる。
        """
        await self._repository.acquire_write_lock()
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        definition, sort_order = existing[axis_id]
        if not definition.is_published:
            return  # 既に下書きなら何もしない（べき等）
        await self._repository.upsert(definition.model_copy(update={"is_published": False}), sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)
