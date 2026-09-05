"""評価軸レジストリの起動時ロード＋管理API書き込み直後の反映。

`domain.axis_definitions.AXIS_DEFINITIONS`はプロセス起動時に一度だけ定義される定数という
前提で、評価ホットパス（evaluation.py/difficulty.py等、10箇所近く）から同期的に読まれている。
DBを実データソースにしつつこの既存の同期アクセス方法を一切変えずに済むよう、
「モジュールレベルの同じdictオブジェクトを、決まった2つのタイミングでin-placeに書き換える」
push型の更新にする（辞書オブジェクト自体を再代入すると`from ... import AXIS_DEFINITIONS`で
束縛済みの参照先が古いままになるため、必ず`.clear()`+`.update()`で中身だけを差し替える）。

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

    DB未接続・0行・未知参照はコード内蔵の既定値へフォールバックせずfail-fastする。
    呼び出し元（main.pyのlifespan）はこの例外を捕捉せず、アプリの起動自体を失敗させる。
    「DBが正で、コードとの不整合（migration未適用等）があれば起動が落ちる」という
    単純な運用にすることで、検知が起動ログの目視だけに依存し気づかれないまま
    放置されるリスクを構造的に無くす。
    """


# `AXIS_DEFINITIONS`以外のコードがaxis_idを文字列として直接ハードコード
# 参照している軸。削除されると、is_publishedの状態に関わらずアプリが壊れる。
# is_publishedとは独立の制約で、下書きへ戻した後（unpublish→delete）でも
# 削除できないようにする。現時点で該当する軸は無い——各軸の性質（`time_scope`・
# `dedicated_way_value_layer`等の宣言的フィールド）を汎用ロジックが読む設計に
# なっているため、axis_idを直接ハードコード参照するコードは存在しない。将来、
# axis_idをハードコード参照するコードが増えた場合はここへ追加する。
_CODE_COUPLED_AXIS_IDS: frozenset[str] = frozenset()


def _find_unknown_references(definitions: dict[str, AxisDefinition]) -> dict[str, list[str]]:
    """各軸のshapeが参照する材料id・軸idのうち、`MATERIAL_CATALOG`にも同じ`definitions`内の
    軸idにも存在しないものを検出する。

    DBのaxis_definitionsテーブルは「行はあるがmigrationが半端に古い」状態になりうる
    （旧shape_paramsが削除済み材料idを参照し続けている等）。Pydanticのバリデーション
    （`AxisShape`）はshapeの構造だけを検証し材料の実在は見ないため、この種の「行として読める
    が意味的には古い」状態は例外を送出せず素通りする。`AxisDefinition.materials`
    （domain/axis_definitions.py）が既に材料id・軸id参照の一覧を提供しているため、ここでは
    それを`is_known_material`と`definitions`のキー集合に照らして未知参照を洗い出すだけでよい。
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

    DB未接続・axis_definitionsテーブル0行（=migration未適用、またはテストの
    `Base.metadata.create_all`のようにテーブルだけ作られてシードされていない環境）・
    未知の材料/軸参照（migration適用が半端で旧shape_paramsが削除済み材料を参照し
    続けているケース）のいずれかを検出した場合、`AxisDefinitionSyncError`を
    送出する（fail-fast）。呼び出し元（main.pyのlifespan）はこれを捕捉しないため、
    DBが期待する状態でなければアプリの起動自体が失敗する。

    `AXIS_DEFINITIONS`はPython literalを持たない。DBが全軸の唯一の正本で、
    この関数が唯一のロード経路であり、Python側にフォールバック用の既定値は
    一切残っていない。

    0行を検知対象に含めても、管理API側で「最後の1軸は削除できない」制約
    （AxisRegistryAdminService.delete参照）を設けているため、正常適用後のテーブルが
    運用中に意図せず空になることは無い。
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
            "軸定義DBに未知の材料/軸参照を検出しました"
            f"（migration未適用・DB定義が半端に古い可能性、改善計画T294/T295参照） unknown={unknown_references}"
        )
    logger.info("軸定義をDBから読み込みました axes=%d", len(definitions))
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(definitions)
    # タイル単位の静的Edge×公開軸スコア行列キャッシュ（tile_score_matrix_cache）は
    # 軸定義の内容が変わるとタイル座標単位のキーだけでは古いスコアと見分けられないため、
    # AXIS_DEFINITIONS更新と同じタイミングで無効化を判定する（`await`を挟まない同期
    # ブロックのため、他のコルーチンが新旧混在の中間状態を観測することはない）。
    # graph_material_cache（EdgeMaterialBundle等の材料そのもの）は意図的に温存する——
    # 軸編集直後の最初のリクエストがDBへ再問い合わせせずに済む設計。
    # 本関数はアプリ起動時（main.pyのlifespan）にも軸定義が実際には変わっていなくても
    # 必ず1回呼ばれるため、無条件で`tile_score_matrix_cache.clear()`すると、デプロイの
    # たびにディスク永続化済みのスコア行列キャッシュを丸ごと再構築することになる。
    # `sync_disk_cache_with_axis_revision`は`axis_registry_meta.revision`を使い、
    # 軸定義が実際に変わった場合のみディスクも削除する。
    revision = await repository.get_revision()
    tile_score_matrix_cache.sync_disk_cache_with_axis_revision(revision)


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
        # 読み取り→Python側での検証→書き込みの手順全体をadvisory lockで
        # 直列化する（TOCTOUレース対策、axis_definition_repository.py: acquire_write_lock
        # のdocstring参照）。
        await self._repository.acquire_write_lock()
        # 存在チェック・排他チェック・sort_order算出の全てを
        # list_all_with_sort_order()の1回の呼び出しから賄う。
        existing = await self._repository.list_all_with_sort_order()
        if definition.axis_id in existing:
            raise ValueError(f"axis_id={definition.axis_id} は既に存在します")
        # axis_idが既知の材料idと衝突していないか検査する。衝突すると
        # evaluate_axes_scalar/evaluate_axis_array（domain/axis_definitions.py）が
        # 評価結果をmaterials辞書へ`materials_with_axes[axis_id] = value`で書き込む際、
        # 同名の生材料値を黙って上書きし、それ以降に評価される軸が壊れる
        # （axis_dependenciesは既知材料名を依存として数えないため評価順の保証も効かない）。
        # axis_idはupdate時に変更されないため、このチェックはcreate時のみでよい。
        if is_known_material(definition.axis_id):
            raise ValueError(f"axis_id={definition.axis_id} は既存の材料idと衝突しています（T296）")
        # 材料の排他帰属チェック（registry.pyの原則を計算系レジストリへ移植）。
        # 新規軸が既存軸の材料を黙って再利用し二重計上が混入する事故を構造的に防ぐ。
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        # 他の軸から参照されている内部軸を誤って公開させない。
        check_internal_axis_not_published(definition, existing_definitions)
        # 軸間参照（内部軸→公開軸の階層構造）に循環が無いか検証する。
        # 参照先axis_idが存在しない場合はAxisDefinitionPayload._check_materials_are_known
        # （router層）で既に弾かれている前提のため、ここではAXIS_DEFINITIONS.keys()を
        # is_known_axis_idの集合として使うtopological_axis_orderへそのまま委ねる。
        topological_axis_order({**existing_definitions, definition.axis_id: definition})
        sort_order = max((order for _, order in existing.values()), default=-1) + 1
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def update(self, axis_id: str, definition: AxisDefinition) -> None:
        # TOCTOUレース対策（create()と同じ、acquire_write_lockのdocstring参照）。
        await self._repository.acquire_write_lock()
        # axis_id存在チェック・sort_order取得・排他チェックの全てを
        # list_all_with_sort_order()の1回の呼び出しから賄う。
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        existing_definition, sort_order = existing[axis_id]
        # 公開済み軸は不変（複製して新しい下書き軸として改良する導線を
        # UI側に用意する）。既存の公開状態を見て判定するため、payload側のis_published
        # 値には関わらず拒否する（公開済みを装って未公開のふりをして更新を通す抜け道を防ぐ）。
        # ただしdefinition（更新後の内容）を渡すことで、表示専用フィールド
        # のみの差分なら例外的に許可する（check_publish_immutability/is_cosmetic_only_update参照）。
        check_publish_immutability(existing_definition, "updated", definition)
        # 自分自身（axis_id）は比較対象から除外される
        # （check_material_exclusivityが同一キーをスキップする）ため、材料構成を
        # 変えない・変える更新のどちらも自己衝突しない。
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        # 他の軸から参照されている内部軸を誤って公開させない。
        check_internal_axis_not_published(definition, existing_definitions)
        # 軸間参照の循環検証（createと同じ、自分自身は上書きで置き換える）。
        topological_axis_order({**existing_definitions, axis_id: definition})
        await self._repository.upsert(definition, sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def delete(self, axis_id: str) -> None:
        # TOCTOUレース対策（create()と同じ、acquire_write_lockのdocstring参照）。
        await self._repository.acquire_write_lock()
        # 重みの妥当性検証は型・範囲チェックのみ（ADR「Stage D設計メモ」）だが、
        # 「レジストリを空にできる」ことは重みの是非とは別次元の構造的な問題
        # （削除後のrefresh_axis_definitionsが0行を検知しAxisDefinitionSyncErrorを
        # 送出する）のため、最後の1軸だけは削除できないようにする。
        existing = await self._repository.list_all()
        if axis_id in existing and len(existing) == 1:
            raise ValueError("最後の1軸は削除できません")
        # is_publishedの状態（下書きへ戻した後含む）に関わらず、
        # コードが名前で直接依存している軸は削除させない。
        if axis_id in _CODE_COUPLED_AXIS_IDS and axis_id in existing:
            raise ValueError(f"axis_id={axis_id} はコードから直接参照されているため削除できません")
        if axis_id in existing:
            # 公開済み軸の削除も不変制約の対象（updateと同じ理由）。
            check_publish_immutability(existing[axis_id], "deleted")
        # 既存のAPIリクエストがこのaxis_idを重みキーとして参照していた場合、削除直後から
        # RoutePreferenceのバリデーション（unknown key）でルート生成が壊れうる（上書き無しの
        # 既定値は常にAXIS_DEFINITIONS由来へ一本化済みのため、この経路は上書きしている
        # クライアントのみが対象）。この整合性チェックは意図的に実装しない——公開済み軸は
        # 上のガードでそもそも削除できず、削除できるのは常に下書き（is_published=False、
        # 一般ユーザーからは`GET /api/axis-catalog`経由で見えていない）軸のみのため、
        # 削除時点で一般ユーザーの保存設定がこのaxis_idを参照している状況自体が起こらない
        # （docs/decisions/t221-axis-registry.md「Stage D拡張3」参照）。
        deleted = await self._repository.delete(axis_id)
        if not deleted:
            raise KeyError(axis_id)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def unpublish(self, axis_id: str) -> None:
        """公開済み軸を下書き（is_published=False）へ戻す。

        `update()`は`check_publish_immutability`で公開済み軸への変更を一律拒否するため、
        「公開フラグの反転だけを許す」専用操作として独立させた。評価ロジックに影響する
        フィールドの変更は引き続きupdate()経由では拒否されたままで（表示専用フィールドのみ
        例外だが、この原則自体は変えない）、下書きへ戻った後は通常のupdate()経路で
        自由に再編集・再公開できる（複製ではなく同一axis_idのまま行き来する、
        データは失われない）。

        呼び出し側（api/routers/axis_admin.py）は、この呼び出しが成功した直後の
        レスポンスで一般ユーザーに`is_published=False`を伝える。フロント側
        （RouteSettingsPanel）は`GET /api/axis-catalog`が返す公開軸集合の変化に合わせて
        routePreferenceのキーを自己修復する前提（ADR「Stage D設計メモ」）——これが無いまま
        本メソッドだけ単独で使うと、旧設定を保持したブラウザで次回のルート生成が
        RoutePreferenceWeightsのキー完全一致検証で422になるため、フロント実装とセットで
        使うこと。
        """
        # TOCTOUレース対策（create()と同じ、acquire_write_lockのdocstring参照）。
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
