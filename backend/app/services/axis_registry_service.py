"""評価軸レジストリの起動時ロード＋管理API書き込み直後の反映（改善計画T221 Stage D）。

`domain.axis_definitions.AXIS_DEFINITIONS`はプロセス起動時に一度だけ定義される定数という
前提で、評価ホットパス（evaluation.py/difficulty.py等、10箇所近く）から同期的に読まれている。
Stage DでDBを実データソースへ昇格させた後もこの既存の同期アクセス方法を一切変えずに済むよう、
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
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

logger = logging.getLogger("ridecompass.axis_registry")

# 改善計画T295: コード内蔵の既定axis_id集合（モジュールimport時、AXIS_DEFINITIONSが
# まだ一度もrefresh_axis_definitionsで上書きされていない時点のスナップショット）。
# refresh_axis_definitionsが呼ばれるたびに、この集合とDB側集合の差分をログへ出し、
# 「GUIで新規軸を作った」「削除済み軸がDBに残っている」等の意図した/しない差分を
# 常に目視できるようにする（起動ログの目視以外に検知手段が無かったT294の教訓）。
_CODE_BUILTIN_AXIS_IDS: frozenset[str] = frozenset(AXIS_DEFINITIONS)


def _find_unknown_references(definitions: dict[str, AxisDefinition]) -> dict[str, list[str]]:
    """各軸のshapeが参照する材料id・軸idのうち、`MATERIAL_CATALOG`にも同じ`definitions`内の
    軸idにも存在しないものを検出する（改善計画T295）。

    DBのaxis_definitionsテーブルは「行はあるがmigrationが半端に古い」状態になりうる
    （T294: migration 0017適用・0018未適用のような組み合わせで、旧shape_paramsが
    削除済み材料id[例: car_stress_level]を参照し続けていた）。Pydanticのバリデーション
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

    DB未接続・axis_definitionsテーブル未migration・0行（=migration未適用、またはテストの
    `Base.metadata.create_all`のようにテーブルだけ作られてシードされていない環境）の場合は
    WARNINGログを出し、domain/axis_definitions.py内蔵の既定値のまま動作を続ける
    （本番でmigration適用がデプロイに遅れて追いつかない既知のリスクへの安全側動作、
    docs/improvement-plan.md T74参照）。この安全側フォールバックにより、本migrationを
    本番へ適用するまでの間は評価の振る舞いが一切変わらない。

    0行をフォールバック対象に含めても、管理API側で「最後の1軸は削除できない」制約
    （AxisRegistryAdminService.delete参照）を設けているため、正常適用後のテーブルが
    運用中に意図せず空になることは無い。

    **「安全側フォールバック」の実際の限界（改善計画T295、T294の教訓を受けた訂正）**:
    上記の0行・例外という2条件は「テーブルが全く読めない」状態しか検知できない。
    「行はあるが一部の軸が削除済みの材料id・axis_idを参照している」ような**半端に古い**
    状態（T294で実際に発生。0017適用・0018未適用の環境で、旧car_stress行が削除済み材料
    car_stress_levelを参照し続けていたが、0018のカラム不在によるSELECT自体の例外という
    **偶然**でしか検知できていなかった）は、この2条件のどちらにも該当せず、読み込みに
    成功した内容をそのままAXIS_DEFINITIONSへ反映してしまう。`_find_unknown_references`が
    この種の状態を明示的に検出し、検出時はDB内容を採用せずコード内蔵の既定値へ
    フォールバックする（0行・例外と同じ安全側動作）。この検証を経て初めて
    「読み込んだ内容を採用してよい」という意味での安全側フォールバックが成立する。
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
    unknown_references = _find_unknown_references(definitions)
    if unknown_references:
        logger.error(
            "軸定義DBに未知の材料/軸参照を検出しました。コード内蔵の既定値を使用します"
            "（migration未適用・DB定義が半端に古い可能性、改善計画T294/T295参照） unknown=%s",
            unknown_references,
        )
        return
    # 改善計画T295: axis_id集合の差分は「良い/悪い」を判定できない（GUIで作った軸が
    # コードに無いのは正常）ため、常にINFOで出す（docs/logging.md「起動時の構成
    # スナップショット」）。差分が無い場合も空リストのまま出力し、「この検証が実際に
    # 走った」ことをログから確認できるようにする。
    missing_in_db = sorted(_CODE_BUILTIN_AXIS_IDS - set(definitions))
    extra_in_db = sorted(set(definitions) - _CODE_BUILTIN_AXIS_IDS)
    logger.info(
        "軸定義をDBから読み込みました axes=%d code_only=%s db_only=%s",
        len(definitions), missing_in_db, extra_in_db,
    )
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(definitions)


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
        # 改善計画T296: axis_idが既知の材料idと衝突していないか検査する。衝突すると
        # evaluate_axes_scalar/evaluate_axis_array（domain/axis_definitions.py）が
        # 評価結果をmaterials辞書へ`materials_with_axes[axis_id] = value`で書き込む際、
        # 同名の生材料値を黙って上書きし、それ以降に評価される軸が壊れる
        # （axis_dependenciesは既知材料名を依存として数えないため評価順の保証も効かない）。
        # axis_idはupdate時に変更されないため、このチェックはcreate時のみでよい。
        if is_known_material(definition.axis_id):
            raise ValueError(f"axis_id={definition.axis_id} は既存の材料idと衝突しています（T296）")
        # 改善計画T268: 材料の排他帰属チェック（registry.pyの原則を計算系レジストリへ移植）。
        # 新規軸が既存軸の材料を黙って再利用し二重計上が混入する事故を構造的に防ぐ。
        existing_definitions = {aid: d for aid, (d, _) in existing.items()}
        check_material_exclusivity(definition, existing_definitions)
        # T311フォローアップ: 他の軸から参照されている内部軸を誤って公開させない。
        check_internal_axis_not_published(definition, existing_definitions)
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
        # T311フォローアップ: 他の軸から参照されている内部軸を誤って公開させない。
        check_internal_axis_not_published(definition, existing_definitions)
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
        # 既存のAPIリクエストがこのaxis_idを重みキーとして参照していた場合、削除直後から
        # RoutePreferenceのバリデーション（unknown key）でルート生成が壊れうる（改善計画T316:
        # 上書き無しの既定値は常にAXIS_DEFINITIONS由来へ一本化済みのため、この経路は
        # 上書きしているクライアントのみが対象）。この整合性チェックは意図的に実装しない——
        # 公開済み軸は上のガードで
        # そもそも削除できず、削除できるのは常に下書き（is_published=False、一般ユーザー
        # からは`GET /api/axis-catalog`経由で見えていない）軸のみのため、削除時点で
        # 一般ユーザーの保存設定がこのaxis_idを参照している状況自体が起こらない
        # （改善計画T302、docs/decisions/t221-axis-registry.md「Stage D拡張3」で確定）。
        deleted = await self._repository.delete(axis_id)
        if not deleted:
            raise KeyError(axis_id)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)

    async def unpublish(self, axis_id: str) -> None:
        """公開済み軸を下書き（is_published=False）へ戻す（改善計画T302）。

        `update()`は`check_publish_immutability`で公開済み軸への変更を一律拒否するため、
        「公開フラグの反転だけを許す」専用操作として独立させた。他フィールドの変更は
        引き続きupdate()経由では拒否されたままで、「公開済みは編集不可」という
        T271の原則自体は変えない。下書きへ戻った後は通常のupdate()経路で自由に
        再編集・再公開できる（複製ではなく同一axis_idのまま行き来する、データは
        失われない）。

        呼び出し側（api/routers/axis_admin.py）は、この呼び出しが成功した直後の
        レスポンスで一般ユーザーに`is_published=False`を伝える。フロント側
        （RouteSettingsPanel）は`GET /api/axis-catalog`が返す公開軸集合の変化に合わせて
        routePreferenceのキーを自己修復する前提（同ADR）——これが無いまま本メソッドだけ
        単独で使うと、旧設定を保持したブラウザで次回のルート生成がRoutePreferenceWeights
        のキー完全一致検証で422になるため、フロント実装とセットで使うこと。
        """
        existing = await self._repository.list_all_with_sort_order()
        if axis_id not in existing:
            raise KeyError(axis_id)
        definition, sort_order = existing[axis_id]
        if not definition.is_published:
            return  # 既に下書きなら何もしない（べき等）
        await self._repository.upsert(definition.model_copy(update={"is_published": False}), sort_order)
        await self._repository.commit()
        await refresh_axis_definitions(self._repository)
