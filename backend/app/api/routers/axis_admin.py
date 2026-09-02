"""評価軸定義のCRUD管理API（改善計画T221 Stage D、ADR: docs/decisions/t221-axis-registry.md）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`をDBの内容と同期させる書き込み口。
ルート生成の振る舞いを直接変えられるため、他のエンドポイントと異なり認可を要求する
（require_admin_basic_auth）。GUI編集画面（Stage E）は本APIの上に構築する想定で
スコープ外。
"""

from typing import Awaitable, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import DBAPIError

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_axis_registry_admin_service
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisCategory,
    AxisDefinition,
    AxisShape,
    BreakpointLinearShape,
    CategoricalShape,
    PriorityCondition,
)
from app.domain.axis_display import axis_display_for
from app.domain.material_catalog import is_known_material, material_dtype
from app.domain.registry import AxisDisplaySpec
from app.services.axis_registry_service import AxisRegistryAdminService

router = APIRouter(prefix="/api/admin/axis-definitions", tags=["axis-admin"])

_T = TypeVar("_T")


async def _guard_db_errors(awaitable: Awaitable[_T]) -> _T:
    """軸スタジオCRUDのDB例外を診断可能な503へ変換する（migration適用ラグの実障害を受けた対応）。

    `refresh_axis_definitions`（axis_registry_service.py）はDB読み込み失敗時にコード内蔵の
    既定値へ安全側フォールバックするが、それは「一般ユーザー向け画面の表示を止めない」ための
    設計で、軸スタジオ（本ルーター）のCRUDには同じフォールバックは適さない——編集対象は常に
    DBの実データそのものであるべきで、DB障害時に古い既定値を編集画面に出すと気付かないまま
    上書きしてしまう危険がある。ここでは代わりに、DBAPIError（接続失敗・migration未適用による
    カラム不在など）だけを捕捉し、未処理の素の500ではなく原因の当たりが付くメッセージを返す
    （ValueError/KeyErrorは呼び出し元の既存except節がそのまま扱うため対象外）。
    """
    try:
        return await awaitable
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "軸定義DBへのアクセスに失敗しました。migration未適用の可能性があります"
                "（backend/scripts/apply_migrations.pyの適用状況を確認してください）"
            ),
        ) from exc


class AxisDefinitionFields(BaseModel):
    """`AxisDefinitionPayload`（書き込み）・`AxisDefinitionResponse`（読み取り）が
    共有するフィールド定義のみを持つ基底クラス（レビュー指摘の修正）。

    以前は`AxisDefinitionResponse(AxisDefinitionPayload): pass`という継承で、
    書き込み専用のバリデータ（`_check_materials_are_known`）まで読み取りレスポンスに
    引き継いでしまっていた。`material_catalog.py`は「材料は今後コード変更で増減
    しうる」設計のため、将来ある材料を削除・リネームした際、DBに永続化済みの
    既存軸がまだその材料idを参照していると、一覧・単体取得（`_to_response`）が
    Pydantic ValidationErrorで未捕捉の500になる抜け穴があった——読み取りは
    「DBの内容をそのまま返す」だけであるべきで、書き込み時点の妥当性を再検証すべき
    ではない。
    """

    axis_id: str
    shape: AxisShape
    default_weight: float = Field(ge=0)
    # 改善計画T269: 一般向けルート設定画面（RouteSettingsPanel）がGET /api/axis-catalog
    # 経由で表示する表示名・説明・分類。labelは必須（表示名の無い軸はUIに出せないため）、
    # description/categoryは既存の呼び出し慣習（省略可な補助情報）に合わせ既定値を持つ。
    label: str
    description: str = ""
    category: AxisCategory = "推定"
    # 改善計画T271: 公開状態（一般向けGET /api/axis-catalogへ出るか）。既定Falseは
    # 「新規作成した軸はまず下書き」という安全側の初期値。公開済み軸への更新・削除は
    # AxisRegistryAdminServiceが拒否する（このPayload自体はis_published=falseで送っても
    # 既存が公開済みなら通らない。ただし改善計画T501: 表示専用フィールドのみの差分は
    # 例外的に許可する、サービス層のcheck_publish_immutability/is_cosmetic_only_update参照）。
    is_published: bool = False
    # 改善計画T292: 0次条件（探索除外のハードフィルタとは別の、評価を優先確定する条件。
    # domain/axis_definitions.py: PriorityCondition参照）。レビュー指摘の修正:
    # 以前はこのフィールド自体が管理APIのリクエスト/レスポンスに露出しておらず、
    # DB永続化層（axis_definition_repository.py）にも書き込まれなかったため、
    # 軸スタジオ経由では設定も参照もできなかった。
    priority_overrides: list[PriorityCondition] = Field(default_factory=list)
    # 改善計画T310: 地図チップ表示要素（既存軸だけ特別扱いしていたSECONDARY_AXIS_ICONS等の
    # 軸id→値の手書き辞書を撤去し、軸スタジオから登録できるようにしたもの）。全て省略可
    # （未設定はフロント側の汎用フォールバックに委ねる、動作は壊れない）。
    icon_id: str | None = None
    chip_label: str | None = None
    panel_hint: str | None = None
    # 改善計画T318: falseなら地図上チップ・地図の見え方パネルの両方からこの軸を丸ごと
    # 除外する（domain/axis_definitions.py: AxisDefinition.show_map_iconのdocstring参照）。
    # 旧proxy_hint（専用地図レイヤーを持たない軸向けの代役案内文）はこの真偽値ON/OFFに
    # 置き換わり撤去した。
    show_map_icon: bool = True
    # 改善計画T352: axis_idハードコード分岐を性質ベースの宣言的フィールドへ汎用化した
    # もの（domain/axis_definitions.py: AxisDefinition.time_scopeのdocstring参照）。
    # AxisComposer.tsx（GUIフォーム）は現時点で編集UIを持たない（管理API経由の
    # 直接編集のみ対応）。
    time_scope: Literal["always", "night_only"] = "always"
    # 改善計画T404: 地図の色分けしきい値だけを差し替える軽量な上書き（domain/
    # axis_definitions.py: AxisDefinition.display_thresholds_overrideのdocstring参照）。
    # 旧display_override（TileInputSpecの構造が複雑なためGUI編集を持てなかった生JSON
    # 上書き、改善計画T409でフィールド・DBカラムごと削除済み）と異なり、AxisComposer.tsx
    # （GUIフォーム）が「数値の配列を編集する」という単純なUIで直接編集できる
    # （バリデーションは下のAxisDefinitionPayload._check_display_thresholds_override_
    # is_ascending参照）。
    display_thresholds_override: list[float] | None = None
    # 改善計画T513: display_thresholds_overrideと対になる、段階ごとの体感ラベルの軽量な
    # 上書き（domain/axis_definitions.py: AxisDefinition.display_band_labels_overrideの
    # docstring参照）。設定する場合はdisplay_thresholds_overrideも設定済みで要素数が
    # 段階数と一致すること（バリデーションは下のAxisDefinitionPayload._check_display_
    # band_labels_override参照）。
    display_band_labels_override: list[str] | None = None
    # この軸が専用のway_id→値配信レイヤー（Redis経由、domain/axis_definitions.py:
    # AxisDefinition.dedicated_way_value_layerのdocstring参照）を持つかの宣言。
    # time_scopeと同じ理由でAxisComposer.tsx（GUIフォーム）は現時点で編集UIを
    # 持たない（管理API経由の直接編集のみ対応）。
    dedicated_way_value_layer: bool = False
    # 改善計画T458: dedicated_way_value_layer=trueの軸のみ意味を持つ（domain/
    # axis_definitions.py: AxisDefinition.dynamic_way_value_needs_time/
    # dynamic_way_value_needs_bearingのdocstring参照）。同じくGUI編集UIは現時点で未対応。
    dynamic_way_value_needs_time: bool = False
    dynamic_way_value_needs_bearing: bool = False


class AxisDefinitionPayload(AxisDefinitionFields):
    """作成・更新リクエストボディ。妥当性検証は型・範囲チェックのみ

    （極端な重み設定に対する意味的な歯止めは設けない、2026-08-24ユーザー判断。
    default_weightの非負制約はRoutePreferenceWeights（routers/routes.py）と同じ）。
    """

    @field_validator("chip_label")
    @classmethod
    def _check_chip_label_length(cls, value: str | None) -> str | None:
        """改善計画T310（ユーザー指摘、2026-08-25）: 地図チップは4文字以下を前提とした
        固定サイズのタイル（MapOverlayControls.module.css）で設計されており、正式名
        （label、例:「車の圧迫感」5文字）をそのまま出すとレイアウトが崩れる。chip_labelを
        設定する場合は必ず4文字以下であることをここで検証する（未設定=Noneはこの
        フィールド単体では対象外——label側の制約は`_check_label_length_or_chip_label`
        [下記model_validator]がまとめて検証する）。
        """
        if value is not None and len(value) > 4:
            raise ValueError(f"chip_label must be 4 characters or fewer (got {len(value)}: {value!r})")
        return value

    @model_validator(mode="after")
    def _check_label_length_or_chip_label(self) -> "AxisDefinitionPayload":
        """コードレビュー指摘の修正: 上のfield_validatorは「chip_labelが明示的に4文字を
        超える場合」だけを弾いており、本来の再発防止対象だった「chip_label未設定のまま
        labelが4文字を超える」経路（フォールバック先のlabelそのものに長さ制約が無い
        ため、chip_labelを設定し忘れた新規軸で同じレイアウト崩れが再発する）を防げて
        いなかった。chip_label未設定時はlabelの長さも検証する。
        """
        if self.chip_label is None and len(self.label) > 4:
            raise ValueError(
                f"label is longer than 4 characters ({len(self.label)}: {self.label!r}); "
                "set chip_label explicitly (4 characters or fewer) for the map chip"
            )
        return self

    @field_validator("display_thresholds_override")
    @classmethod
    def _check_display_thresholds_override_is_ascending(cls, value: list[float] | None) -> list[float] | None:
        """改善計画T404: 色分けの段階境界値は昇順でなければ意味を持たない
        （`buildAxisRampColorExpression`[axisLayers.ts]のMapLibre `step` expressionが
        昇順を前提とする——降順・同値混在だと未定義動作になる）。空リストも「境界が
        0個で常に1段階」を意味してしまい実質意味が無いため、設定する場合は最低1件を要求する
        （axis_admin.py: chip_labelの4文字制約と同じ、入力欄の少なさに比べて事故りやすい
        値のためAPIレベルで弾く）。"""
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError("display_thresholds_override is set but empty; provide at least one threshold or omit it")
        if any(b <= a for a, b in zip(value, value[1:])):
            raise ValueError(f"display_thresholds_override must be strictly ascending, got {value!r}")
        return value

    @model_validator(mode="after")
    def _check_display_band_labels_override(self) -> "AxisDefinitionPayload":
        """改善計画T513: 段階ラベルはdisplay_thresholds_overrideが決める段階数
        （`len(display_thresholds_override)+1`）と1:1対応する必要がある。しきい値の
        方が未設定（自動導出任せ）のまま段階数だけラベルで決め打ちすると、実際に
        表示される段階数（自動導出の結果次第で変わりうる）とラベルの対応が保証
        できないため、しきい値も明示済みであることを必須にする。"""
        if self.display_band_labels_override is None:
            return self
        if self.display_thresholds_override is None:
            raise ValueError(
                "display_band_labels_override requires display_thresholds_override to be set "
                "(band count must be known and fixed)"
            )
        expected_band_count = len(self.display_thresholds_override) + 1
        if len(self.display_band_labels_override) != expected_band_count:
            raise ValueError(
                f"display_band_labels_override must have {expected_band_count} entries "
                f"(display_thresholds_override has {len(self.display_thresholds_override)} thresholds), "
                f"got {len(self.display_band_labels_override)}"
            )
        return self

    @model_validator(mode="after")
    def _check_materials_are_known(self) -> "AxisDefinitionPayload":
        """改善計画T277: shapeが参照する材料が`domain/material_catalog.py:
        MATERIAL_CATALOG`の既知材料であることを検証する（未知の文字列を送っても
        通ってしまっていた抜け穴を塞ぐ）。材料は今後コード変更で増減しうるため、
        判定は`MATERIAL_CATALOG`を都度参照する形にし、本モデル側に材料一覧を
        複製しない。

        あわせて、材料のdtype（numeric/boolean/categorical）がshape種別の前提と
        一致するかも検証する（レビュー指摘で発見: 以前は存在チェックのみで、例えば
        `CategoricalShape`にnumeric材料[例: stop_count_per_km]を指定しても素通り
        していた。`axis_templates.evaluate_categorical`はmapping.get(value, None)で
        マッピング済みキーしか引けないため、想定外dtypeの値は常にNone/NaNとなり、
        その軸は全Edgeで恒久的に欠損扱いになる——エラーもログも一切出ないまま）。
        `CategoricalShape`はboolean/categorical材料（改善計画T292でstr多値対応）、
        `BreakpointLinearShape`はnumeric/boolean材料を前提とする（改善計画T353:
        `evaluate_axis_scalar`の計算は`value * term.weight`という単純な乗算のため、
        bool値でも`True==1.0`/`False==0.0`として数値的に正しく計算される——
        CategoricalShapeのmapping.get(value)のような「想定外dtypeが静かに欠損化する」
        問題はBreakpointLinearShapeには無い。改善計画T396で撤去した旧`FlagSumShape`
        もboolean材料前提だったが、統合後は全termがboolean材料であることの構造上の
        強制は無く、numeric/boolean混在も許容する（`car_stress_bicycle_infra_
        adjustment`[migration経由で作成、本バリデーション導入前から存在]が実際に
        boolean材料4件をtermsに使い運用されてきた実績があり、このバリデーションが
        numericのみを許可していたのは意図的な安全策ではなく、単に見落としだった）。

        改善計画T292: materialsは`MATERIAL_CATALOG`の材料idだけでなく、他の軸の
        axis_id（軸の階層構造、内部軸→公開軸）も指せる。軸参照はdtypeチェックの
        対象外とする（評価結果は常に数値[0-100のdifficulty]のため、単純な材料の
        dtype検証とは別の話。循環参照・参照先の存在チェックは
        `AxisRegistryAdminService.create/update`側で行う）。
        """
        if isinstance(self.shape, BreakpointLinearShape):
            materials = [term.material for term in self.shape.terms]
            expected_dtypes = {"numeric", "boolean"}
            # 改善計画T425（ゼロベース網羅レビュー指摘）: shape.breakpointsのx昇順は
            # `evaluate_breakpoint_linear`（axis_templates.py）のnp.interpが前提とする
            # 不変条件だが、これまで検証が一切無かった（display_thresholds_override側の
            # 同種チェック[_check_display_thresholds_override_is_ascending、改善計画T404]は
            # 色分け表示用の別フィールドで、評価に使うこちらのshape.breakpointsは対象外
            # だった）。昇順でないと補間結果が未定義動作になり、評価時に無警告のまま
            # おかしいスコアが返り続ける。
            xs = [bp[0] for bp in self.shape.breakpoints]
            if any(b <= a for a, b in zip(xs, xs[1:])):
                raise ValueError(f"shape.breakpoints must be strictly ascending by x, got {self.shape.breakpoints!r}")
        else:
            materials = [self.shape.material]
            expected_dtypes = {"boolean", "categorical"}
        unknown = sorted({m for m in materials if not is_known_material(m) and m not in AXIS_DEFINITIONS})
        if unknown:
            raise ValueError(f"unknown material(s)/axis reference(s) in shape: {unknown}")
        mismatched = sorted(
            {m for m in materials if is_known_material(m) and material_dtype(m) not in expected_dtypes}
        )
        if mismatched:
            raise ValueError(
                f"material(s) {mismatched} have the wrong dtype for this shape "
                f"(expected one of {sorted(expected_dtypes)})"
            )
        # コードレビュー指摘の修正: 上のdtypeチェックはmaterialのdtype「クラス」
        # （boolean/categoricalのどちらか）しか見ておらず、CategoricalShape.mapping
        # の実際のキー型（bool値かstr値か）がそのmaterialのdtypeと一致するかは
        # 検証していなかった。例えばhighway（dtype="categorical"、値は"residential"
        # 等の文字列）を参照するCategoricalShapeに{True: 1.0, False: 0.0}という
        # boolキーのmappingを指定してもここまでの検証は通過してしまい、評価時
        # evaluate_categoricalがmapping.get("residential", None)で常にNoneを返す
        # ため、その軸は全Edgeで恒久的に欠損扱いになる（このバリデータ自体が
        # 防ごうとしていたのと全く同型のバグの再発）。CategoricalShapeに限り、
        # mappingキーの型とmaterialのdtypeが一致することも検証する。
        if isinstance(self.shape, CategoricalShape) and is_known_material(self.shape.material):
            dtype = material_dtype(self.shape.material)
            key_types = {type(key) for key in self.shape.mapping}
            expected_key_type = bool if dtype == "boolean" else str
            if key_types and key_types != {expected_key_type}:
                raise ValueError(
                    f"material '{self.shape.material}' has dtype={dtype!r} but mapping keys are "
                    f"{sorted(t.__name__ for t in key_types)} (expected all {expected_key_type.__name__})"
                )
        # 改善計画T425（ゼロベース網羅レビュー指摘）: priority_overrides[*].materialは
        # 上の検証（shapeが参照する材料のみ対象）の対象外だったため、未知の材料id・軸id
        # （typo等）を指定しても保存でき、評価時にmaterials.get(override.material)が
        # 常にNoneを返し0次条件が無警告のまま一切発動しないバグがあった。shapeと同じ
        # 「未知の材料/軸参照」チェックをここでも行う（equalsは文字列固定で比較先の値の
        # 型を問わないため、dtype検証は対象外——boolean/categorical/numericいずれの
        # materialも文字列化して比較できる、_priority_override_matches_scalar参照）。
        unknown_override_materials = sorted(
            {
                cond.material
                for cond in self.priority_overrides
                if not is_known_material(cond.material) and cond.material not in AXIS_DEFINITIONS
            }
        )
        if unknown_override_materials:
            raise ValueError(
                f"unknown material(s)/axis reference(s) in priority_overrides: {unknown_override_materials}"
            )
        return self

    def to_definition(self) -> AxisDefinition:
        """コードレビュー指摘の修正: create/update両エンドポイントが同じ全フィールドを
        手書きコピーしてAxisDefinition(...)を組み立てており、`AxisDefinitionFields`へ
        フィールドを追加するたびに2箇所を同時に直す必要があった（今回のT310でicon_id等
        5フィールドが両方に追加された、CLAUDE.mdが警告する「同期ペアの片側更新漏れ」と
        同型のリスク）。改善計画T467: `AxisDefinitionPayload`は`AxisDefinitionFields`へ
        バリデータのみを足す（フィールドは追加しない）ため、フィールド名の集合は
        `AxisDefinition`（domain/axis_definitions.py）と完全に一致する。手書きの
        16フィールド列挙（片側更新漏れの温床）をmodel_dump()経由の展開へ置き換え、
        フィールド一覧そのものを両クラスの宣言（1箇所ずつ）だけに保つ。"""
        return AxisDefinition(**self.model_dump())


class AxisDefinitionResponse(AxisDefinitionFields):
    """一覧・単体取得のレスポンスボディ。DB由来の既存データをそのまま返すため、
    `AxisDefinitionPayload`の書き込み時専用バリデータ（`_check_materials_are_known`）は
    継承しない（`AxisDefinitionFields`のdocstring参照）。

    `display`（改善計画T404）: `domain/axis_display.py: axis_display_for()`の計算結果
    （`GET /api/axis-catalog`と同じ関数）。軸スタジオのGUI（AxisComposer.tsx）が
    「自動導出が失敗している（kind="none"）ので、この軸の材料には地図表示用のデータ取得
    経路がまだ用意されていない」という注記を出すために必要——下書き軸（is_published=False）
    は`GET /api/axis-catalog`に現れないため、編集中に自己診断できる経路がこの管理APIの
    レスポンスにしか無い。"""

    display: AxisDisplaySpec


def _to_response(definition: AxisDefinition) -> AxisDefinitionResponse:
    """改善計画T467: to_definition()と対になる同期ペア。`AxisDefinitionResponse`は
    `AxisDefinitionFields`へ`display`を1つ足すのみ（フィールドは追加しない）ため、
    16フィールドの手書き列挙をmodel_dump()経由の展開へ置き換える（to_definition()の
    docstring参照）。"""
    return AxisDefinitionResponse(**definition.model_dump(), display=axis_display_for(definition))


@router.get("", dependencies=[Depends(require_admin_basic_auth)])
async def list_axis_definitions(
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> list[AxisDefinitionResponse]:
    definitions = await _guard_db_errors(service.list_all())
    return [_to_response(definition) for definition in definitions.values()]


@router.get("/{axis_id}", dependencies=[Depends(require_admin_basic_auth)])
async def get_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = await _guard_db_errors(service.get(axis_id))
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません")
    return _to_response(definition)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin_basic_auth)])
async def create_axis_definition(
    payload: AxisDefinitionPayload, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = payload.to_definition()
    try:
        await _guard_db_errors(service.create(definition))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition)


@router.put("/{axis_id}", dependencies=[Depends(require_admin_basic_auth)])
async def update_axis_definition(
    axis_id: str,
    payload: AxisDefinitionPayload,
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> AxisDefinitionResponse:
    if payload.axis_id != axis_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="axis_idはURLとボディで一致させてください"
        )
    definition = payload.to_definition()
    try:
        await _guard_db_errors(service.update(axis_id, definition))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    except ValueError as exc:
        # 改善計画T271: 公開済み軸の更新拒否（AxisPublishedImmutableError）。T268の材料
        # 排他チェック（AxisMaterialConflictError）もここを通る——以前はこのexcept節が
        # 無く、更新時の材料衝突が想定外の500になっていた抜け穴も合わせて塞いだ。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition)


@router.delete("/{axis_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin_basic_auth)])
async def delete_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> None:
    try:
        await _guard_db_errors(service.delete(axis_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{axis_id}/unpublish", dependencies=[Depends(require_admin_basic_auth)])
async def unpublish_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    """公開済み軸を下書きへ戻す（改善計画T302）。`update()`と異なり公開済み軸に対しても
    成功する——これが`update()`ではなく専用エンドポイントである理由（is_published以外の
    フィールドは一切変更しない、T271の「公開済みは編集不可」原則を保ったまま公開フラグの
    反転だけに穴を開ける）。下書きへ戻った軸は通常のPUTで再編集・再公開できる。"""
    try:
        await _guard_db_errors(service.unpublish(axis_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    definition = await _guard_db_errors(service.get(axis_id))
    if definition is None:
        # 改善計画T467: assert文は`python -O`実行時に取り除かれる（本番起動コマンドが-Oを
        # 使っていない現状でも、将来変更されると不変条件チェックごと消える不安定な保護に
        # なる）。unpublishが例外なく返った直後のため通常は必ず存在するが、その不変条件を
        # 常に有効な形で守る。
        raise RuntimeError(f"axis_id={axis_id} のunpublish直後にgetが空を返しました（不変条件違反）")
    return _to_response(definition)
