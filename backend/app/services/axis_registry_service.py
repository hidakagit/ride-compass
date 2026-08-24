"""評価軸レジストリの起動時ロード＋管理API書き込み直後の反映（改善計画T221 Stage D）。

`domain.axis_definitions.AXIS_DEFINITIONS`はプロセス起動時に一度だけ定義される定数という
前提で、評価ホットパス（evaluation.py/difficulty.py等、10箇所近く）から同期的に読まれている。
Stage DでDBを実データソースへ昇格させた後もこの既存の同期アクセス方法を一切変えずに済むよう、
「モジュールレベルの同じdictオブジェクトを、決まった2つのタイミングでin-placeに書き換える」
push型の更新にする（辞書オブジェクト自体を再代入すると`from ... import AXIS_DEFINITIONS`で
束縛済みの参照先が古いままになるため、`domain.axis_definitions.replace_axis_definitions`が
`.clear()`+`.update()`で中身だけを差し替える。同関数は評価ホットパスが使う
`topological_axis_order`の結果キャッシュ[`get_axis_evaluation_order`、改善計画T292
フォローアップ]も合わせて無効化するため、AXIS_DEFINITIONSの中身を変える箇所は必ず
この関数を経由すること——直接`.clear()`/`.update()`すると古いキャッシュが残る）。

更新タイミングは以下の2箇所のみ:
1. アプリ起動時（main.pyのlifespanから`refresh_axis_definitions`を1回呼ぶ）
2. 管理API（api/routers/axis_admin.py）が書き込みに成功した直後
   （`AxisRegistryAdminService`が同一プロセス内で完結させるため、ポーリングは不要）

これはinfrastructure/graph_material_cache.pyが採用した「プロセス単位、バージョン照合はしない」
という既存の前提をそのまま踏襲している。複数プロセス・複数ワーカー構成では他プロセスでの
編集がこのプロセスへ即時反映されない制約が残るが、現状の単一プロセスデプロイでは問題にならない
（将来複数ワーカー化する際は、DB側のaxis_registry_meta.revisionをポーリングする方式へ
差し替える。ADR「Stage D設計メモ」参照）。
"""

import logging

from app.domain.axis_definitions import (
    AxisDefinition,
    check_material_exclusivity,
    check_publish_immutability,
    replace_axis_definitions,
    topological_axis_order,
)
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

logger = logging.getLogger("ridecompass.axis_registry")


async def refresh_axis_definitions(repository: AxisDefinitionRepository) -> None:
    """DBの内容でAXIS_DEFINITIONSをin-place更新する。

    DB未接続・axis_definitionsテーブル未migration・0行（=migration未適用、またはテストの
    `Base.metadata.create_all`のようにテーブルだけ作られてシードされていない環境）の場合は
    WARNINGログを出し、domain/axis_definitions.py内蔵の既定値のまま動作を続ける
    （本番でmigration適用がデプロイに遅れて追いつかない既知のリスクへの安全側動作、
    docs/improvement-plan.md T74参照）。この安全側フォールバックにより、本migrationを
    本番へ適用するまでの間は評価の振る舞いが一切変わらない。

    0行をフォールバック対象に含めても、管理API側で「最後の1軸は削除できない」制約
    （AxisRegistryAdminService.delete参照）を設けているため、正常適用後のテーブルが
    運用中に意図せず空になることは無い。
    """
    try:
        definitions = await repository.list_all()
    except Exception as exc:  # noqa: BLE001 起動を止めず内蔵の既定値へ安全側フォールバックする
        logger.warning("軸定義のDB読み込みに失敗、コード内蔵の既定値を使用します error=%r", exc)
        return
    if not definitions:
        logger.warning(
            "axis_definitionsテーブルが空です（migration未適用の可能性）。コード内蔵の既定値を使用します"
        )
        return
    replace_axis_definitions(definitions)
    logger.info("軸定義をDBから読み込みました axes=%d", len(definitions))


class AxisRegistryAdminService:
    """軸定義CRUD管理API（api/routers/axis_admin.py）向けのユースケース層。

    書き込みは1操作=1トランザクション（repositoryのcommit）で確定し、直後に
    `refresh_axis_definitions`でプロセス内キャッシュへ反映する。
    """

    def __init__(self, repository: AxisDefinitionRepository):
        self._repository = repository

    async def list_all(self) -> dict[str, AxisDefinition]:
        return await self._repository.list_all()

    async def get(self, axis_id: str) -> AxisDefinition | None:
        existing = await self._repository.get(axis_id)
        return existing[0] if existing else None

    async def create(self, definition: AxisDefinition) -> None:
        # レビュー指摘の修正: 以前は存在チェック用get()（単一行）と排他チェック用
        # list_all()（全件）を別々に発行しており、後者が前者を情報として完全に
        # 包含するため冗長だった。list_all_with_sort_order()を1回だけ呼び、
        # 存在チェック・排他チェック・sort_order算出（従来は別クエリの
        # next_sort_order()）の全てをここから賄う。
        existing = await self._repository.list_all_with_sort_order()
        if definition.axis_id in existing:
            raise ValueError(f"axis_id={definition.axis_id} は既に存在します")
        # 改善計画T268: 材料の排他帰属チェック（registry.pyの原則を計算系レジストリへ移植）。
        # 新規軸が既存軸の材料を黙って再利用し二重計上が混入する事故を構造的に防ぐ。
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        # 改善計画T292: 軸間参照（内部軸→公開軸の階層構造）に循環が無いか検証する。
        # 参照先axis_idが存在しない場合はAxisDefinitionPayload._check_materials_are_known
        # （router層）で既に弾かれている前提のため、ここではAXIS_DEFINITIONS.keys()を
        # is_known_axis_idの集合として使うtopological_axis_orderへそのまま委ねる。
        topological_axis_order({**existing_definitions, definition.axis_id: definition})
        sort_order = max((order for _, order in existing.values()), default=-1) + 1
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def update(self, axis_id: str, definition: AxisDefinition) -> None:
        # レビュー指摘の修正: 以前はaxis_id存在チェック用get()（単一行、sort_order取得も
        # 兼ねる）と排他チェック用list_all()（全件）を別々に発行しており冗長だった。
        # list_all_with_sort_order()を1回だけ呼び、両方をここから賄う。
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        existing_definition, sort_order = existing[axis_id]
        # 改善計画T271: 公開済み軸は不変（複製して新しい下書き軸として改良する導線を
        # UI側に用意する）。既存の公開状態を見て判定するため、payload側のis_published
        # 値には関わらず拒否する（公開済みを装って未公開のふりをして更新を通す抜け道を防ぐ）。
        check_publish_immutability(existing_definition, "updated")
        # 改善計画T268: 自分自身（axis_id）は比較対象から除外される
        # （check_material_exclusivityが同一キーをスキップする）ため、材料構成を
        # 変えない・変える更新のどちらも自己衝突しない。
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        # 改善計画T292: 軸間参照の循環検証（createと同じ、自分自身は上書きで置き換える）。
        topological_axis_order({**existing_definitions, axis_id: definition})
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def delete(self, axis_id: str) -> None:
        # 重みの妥当性検証は型・範囲チェックのみ（2026-08-24ユーザー判断、ADR「Stage D設計
        # メモ」）だが、「レジストリを空にできる」ことは重みの是非とは別次元の構造的な問題
        # （refresh_axis_definitionsの0件フォールバックと衝突し、削除後にAXIS_DEFINITIONSが
        # 更新されず古いままになる／評価が全軸なしで完全に壊れる）のため、最後の1軸だけは
        # 削除できないようにする。
        existing = await self._repository.list_all()
        if axis_id in existing and len(existing) == 1:
            raise ValueError("最後の1軸は削除できません")
        if axis_id in existing:
            # 改善計画T271: 公開済み軸の削除も不変制約の対象（updateと同じ理由）。
            check_publish_immutability(existing[axis_id], "deleted")
        # route_preference.yamlや既存のAPIリクエストがこのaxis_idを重みキーとして参照して
        # いた場合、削除直後からRoutePreferenceのバリデーション（unknown key）でルート生成が
        # 壊れうる。この整合性チェックは意図的に実装しない（Stage EでGUI編集が実利用される
        # 段階で改めて検討する）。
        deleted = await self._repository.delete(axis_id)
        if not deleted:
            raise KeyError(axis_id)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)
