"""評価軸の定義データと汎用評価関数（改善計画T221 Stage B/C、ADR: docs/decisions/t221-axis-registry.md）。

現行8軸（勾配・向かい風・舗装質・停止密度・車ストレス・事故密度・夜間・自転車インフラ）の
「一次属性由来の材料 → 軸別difficulty(0-100)」変換を、コード（軸ごとの関数）ではなく
**データ（`AXIS_DEFINITIONS`）**として宣言する。変換の計算自体はStage A（T239）の
4テンプレート（`domain/axis_templates.py`）が担い、本モジュールは
「どの材料を・どのテンプレートに・どのパラメータで通すか」だけを持つ。

- 既存テンプレート＋既存材料の組み合わせで表現できる新しい軸は、`AXIS_DEFINITIONS`へ
  1エントリ追加するだけで、スカラー評価（`compute_edge_axis_scores`・区間表示）と
  配列評価（`compute_edge_costs_bulk`のベクトル化経路）の両方へ同時に反映される
  （T240のベクトル化で生じたスカラー/配列二重実装は本モジュールで解消済み。
  `evaluate_axis_scalar`/`evaluate_axis_array`が同じ定義データを読む）。
- breakpoints等の変換パラメータの単一ソースはここ（定数の片側import原則、
  docs/complexity-review-2026-08-16.md）。`domain/difficulty.py`・`domain/night.py`の
  従来関数は本定義を参照する薄いラッパとして残る（外部シグネチャ互換のため）。
- 材料（material）はOSM生タグそのものではなく「評価直前まで解決済みの値」
  （勾配%・風ペナルティm/s・舗装良否・km正規化済み密度・レシピ計算済みレベル・
  タグ由来フラグ）。材料の解決（抽出）は呼び出し元の責務で、材料idごとの意味は
  `AXIS_DEFINITIONS`の各エントリのコメント参照。
- 0次ハードフィルタ（ADRスキーマの`hard_filter`）は軸単位ではなく独立した仕組み
  （`domain/evaluation.py: DEFAULT_HARD_FILTERS`）のままのため、本定義には持たない。
- Stage D（DBテーブル化）・Stage E（GUI編集）は完了済み（軸スタジオ、改善計画T270/T292）。
  改善計画T350で`AXIS_DEFINITIONS`のPython literalも撤去し、`axis_definitions`DBテーブルが
  14軸全ての唯一の正本になった。起動時（`app/services/axis_registry_service.py:
  refresh_axis_definitions`）にDBから読み込みこのモジュールレベルdictへpushするまでは
  空のまま。本モジュールが持つのは型定義（`AxisDefinition`等）と評価用の純粋関数
  （`evaluate_axis_scalar`等）のみで、実データは持たない。新規軸の追加・既存軸の変更は
  他のスキーマ変更と同じく手書きのmigration SQL（`backend/migrations/`）で行う。

欠損値の表現はスカラー経路がNone、配列経路がNaN（従来の`*_difficulty`関数・
`*_difficulty_array`関数と同じ規約）。丸めは区分線形補間系のみ小数1桁
（スカラーはPython `round()`、配列は`np.round`——両者の.X5境界での差異と
実データでの安全性確認はdomain/difficulty.pyの配列版コメント（T240）参照）。
"""

import math
from typing import Annotated, Literal, Mapping, Union

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.domain.axis_templates import (
    evaluate_breakpoint_linear,
    evaluate_categorical,
    evaluate_flag_sum,
)
from app.domain.registry import AxisDisplaySpec


class MaterialTerm(BaseModel):
    """区分線形補間系shapeの入力1件（材料id・線形結合の係数・欠損時の扱い）。

    `required=True`の材料が欠損（スカラーNone/配列NaN）なら軸全体を欠損として扱う。
    `required=False`の材料の欠損は寄与0として残りだけで評価する（stop_density軸の
    「信号等のデータが主、交差点データは補助」という非対称な扱い、改善計画T149）。
    """

    model_config = ConfigDict(frozen=True)

    material: str
    weight: float = 1.0
    required: bool = True


class BreakpointLinearShape(BaseModel):
    """区分線形補間（材料の線形結合→前処理→breakpoints折れ線、両端クランプ、小数1桁丸め）。

    `kind="recipe_then_breakpoint_linear"`は計算上は同一で、材料が軸固有のレシピ判定
    （car_stress: `domain/traffic.py: car_stress_level`）の算出済み結果であることを
    表す命名（ADRの4テンプレート名に対応）。
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["breakpoint_linear", "recipe_then_breakpoint_linear"] = "breakpoint_linear"
    terms: list[MaterialTerm]
    preprocess: Literal["identity", "abs"] = "identity"
    breakpoints: list[tuple[float, float]]


class CategoricalShape(BaseModel):
    """カテゴリ値→定数のマッピング（丸めなし。mappingの値がそのままスコアになる）。

    改善計画T292: `mapping`のキーはbool（旧来のsurface_good等、真偽2値の材料）と
    str（highway/designation等、MATERIAL_CATALOGのdtype="categorical"材料、
    3値以上）の両方を許容する（混在は想定しないが型上は許容）。`evaluate_categorical`
    自体は元々キーの型を問わない汎用実装のため、ここのモデル定義を広げるだけで
    新テンプレートは不要だった。

    キー型は`union_mode="left_to_right"`でbool判定を先に試す（既定のsmart modeだと
    JSON文字列"true"/"false"がboolへ強制変換されずstr型のまま残ってしまい、
    `infrastructure/axis_definition_repository.py`のDB往復でsurface_q等の真偽値材料が
    壊れる回帰があった——実データ検証で発覚、"true"/"false"以外の文字列キーは
    bool変換に失敗してstrへフォールバックするため通常のcategorical材料には影響しない）。
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["categorical"] = "categorical"
    material: str
    mapping: dict[Annotated[Union[bool, str], Field(union_mode="left_to_right")], float]


class FlagSumShape(BaseModel):
    """(boolフラグ材料, 加点)の合計、capでクランプ（丸めなし）。いずれかの材料が
    欠損なら軸全体を欠損として扱う（現行night軸はway_tags未取得時に全フラグが
    まとめて欠損する構造のため、部分欠損の細かい規約は定めない）。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["flag_sum"] = "flag_sum"
    # 改善計画T278のderive_ramp_inputs（domain/axis_display.py: _flag_sum_thresholds）が
    # 達成しうる合計値を全部分集合（2^N-1通り）列挙して求めるため、Nを明示的に上限で
    # 保護する（レビュー指摘: 以前は上限が無く、軸スタジオUIの「+ フラグを追加」で
    # 際限なく増やせた）。現行の「材料の天井」（目論見書7章・歯止め4、材料は全軸合計で
    # MATERIAL_CATALOGの登録数までしか増やせない設計）を踏まえれば実運用でこの上限に
    # 達することは無い想定の、余裕を持った安全弁。
    flags: list[tuple[str, float]] = Field(max_length=12)
    cap: float | None = None


AxisShape = BreakpointLinearShape | CategoricalShape | FlagSumShape


AxisCategory = Literal["観測", "推定", "動的"]


class PriorityCondition(BaseModel):
    """0次条件（改善計画T292）: 探索除外のハードフィルタ（`domain/evaluation.py:
    DEFAULT_HARD_FILTERS`、道路そのものを探索グラフから除外する）とは別の、
    **評価を優先確定する**条件。`material`の値が`equals`と一致する場合、軸の通常計算
    （shape評価）を丸ごとスキップし、`value`をそのままdifficultyとして返す。

    典型例: `motor_vehicle_no`（自動車通行不可）が立っている区間は、highway種別・
    自転車インフラ等の通常の判定に関わらず「車の圧迫感が最も低い」で確定する。
    自転車通行禁止（`bicycle=no`）はこれとは異なり、既存の0次ハードフィルタ
    （`no_bicycle`）で道路そのものが探索から除外されるため、この機構は使わない
    （「探索除外」と「評価の優先確定」は別の概念、docs/improvement-plan.md T292参照）。

    軸固有のPythonコードへベタ書きせず、`AxisDefinition`が共通で持てる宣言的な
    仕組みにすることで、将来の軸追加でも同型のケースをコード変更なしに表現できる
    （「各推定軸に重複して持たせない」というユーザー方針）。
    """

    model_config = ConfigDict(frozen=True)

    material: str
    equals: str
    value: float


class AxisDefinition(BaseModel):
    """1つの評価軸の宣言（ADRの`AxisDefinition`スキーマ）。

    `default_weight`はAPIリクエストで上書きされなかった場合の既定の合成重み
    （`RoutePreference`の既定値の単一ソース、改善計画T316）。

    `label`/`description`/`category`（改善計画T269）は一般向けルート設定画面
    （`RouteSettingsPanel`）が`GET /api/axis-catalog`経由で表示する。従来
    `frontend/src/lib/evaluationAxes.ts`に手書きしていた値をここへ移し、
    軸スタジオ（T270）がGUIから作る新規軸も同じ経路で表示名を持てるようにする
    （`registry.py`側の表示レジストリ[T137/T145b、地図レイヤー専用]とは別物——
    あちらはPython宣言のみでDB化されておらず、GUIで作った軸を表現できないため、
    ルーティング計算を駆動するこちら側に単一ソースを置く）。`category`は
    観測（タグ・POI等の一次属性を直接読む、または単純なフラグ加算のみの軸）／
    推定（複数材料をレシピ・判定式で合成する軸）／動的（時々刻々変わる外部データ由来の軸）
    の3分類（目論見書3章、T267で確定）。

    **軸の階層（改善計画T292）**: `shape`の`MaterialTerm.material`/`CategoricalShape.
    material`等は、`MATERIAL_CATALOG`の材料idだけでなく**他の軸のaxis_id**も指せる
    （評価時、既に計算済みの軸のdifficulty値が`materials`辞書へ材料と同じ扱いで
    混ぜ込まれる。`evaluate_axis_scalar`/`evaluate_axis_array`のシグネチャ・実装は
    無変更、呼び出し側が依存順に評価して結果を`materials`へ書き足すだけ）。これにより
    「highway基準値」「自転車インフラ」等の細かい推定軸（`is_published=False`、
    一般ユーザーには非公開）を、さらに1段合成した「翻訳結果」として公開軸
    （`is_published=True`）を作る、という階層構造を表現できる。`materials`プロパティは
    材料id・軸id両方を区別なく返すため、材料の排他帰属チェック
    （`check_material_exclusivity`）は`MATERIAL_CATALOG`に実在するものだけを対象に
    絞り、軸参照は対象外とする（複数の公開軸が同じ内部軸を参照するのは意図的な共有で
    あり、材料の二重計上とは別の話のため）。
    """

    model_config = ConfigDict(frozen=True)

    axis_id: str
    shape: AxisShape
    default_weight: float
    label: str
    description: str = ""
    category: AxisCategory = "推定"
    # 改善計画T271: 公開済み軸は一般向け`GET /api/axis-catalog`（一般ユーザーの保存設定が
    # axis_idキーで再現されるため、公開後の破壊的変更・削除は他ユーザーの設定を黙って
    # 壊す）に出る一方、下書き軸は管理API（軸スタジオ）でのみ見える。既定Falseは
    # 「新規作成した軸はまず下書き」という安全側の初期値。改善計画T292でこのフラグを
    # 「内部軸（他の軸から参照される専用、恒久的に非公開のまま運用）」の表現にも流用する
    # （新フィールドを増やさず既存の仕組みを再利用する、ユーザー承認済み）。
    is_published: bool = False
    # 改善計画T292: 0次条件（軸の通常計算より前に評価される優先確定ルール）。空リストは
    # 「無し」（従来どおりshapeだけで評価）で、既存6軸の挙動には影響しない。
    priority_overrides: list[PriorityCondition] = Field(default_factory=list)
    # 改善計画T310: 地図チップ表示要素（既存軸だけ特別扱いしていたSECONDARY_AXIS_ICONS等の
    # 軸id→値の手書き辞書を廃止し、軸自身のデータとして持たせる。全て未設定＝Noneが既定で、
    # フロント側は未設定を「汎用フォールバックを使う」の意味で扱う（機能は壊れない）。
    icon_id: str | None = None
    """地図チップのアイコン（frontend/src/components/Map/axisIconPalette.tsxの固定
    パレットからidを選ぶ。未知/未設定のidは汎用アイコン[AxisRampIcon]へフォールバック。
    新しいアイコン形状の追加自体は引き続きコード変更を要する——GUIから任意のSVGを
    登録させる方式はスタイル一貫性・XSSサニタイズのコストが高いためユーザー判断で
    見送った、docs/improvement-plan.md T310参照）。"""
    chip_label: str | None = None
    """地図チップの略称。設定する場合は4文字以内必須（地図チップが固定サイズのタイルの
    ため、axis_admin.py: AxisDefinitionPayload._check_chip_label_lengthが書き込み時に
    検証する）。未設定はlabelをそのまま使う——labelが4文字を超える軸（例:「車の圧迫感」
    5文字）は、そのままだとタイルのレイアウトが崩れるため、その場合は明示的にこの
    フィールドを設定すること。"""
    panel_hint: str | None = None
    """地図の見え方パネル（MapLayersPanel）向けの噛み砕いた説明文。未設定は
    descriptionをそのまま使う（開発者向けの技術説明のため読みにくい場合がある）。"""
    show_map_icon: bool = True
    """falseなら地図上チップ（MapOverlayControls）・地図の見え方パネル
    （MapLayersPanel）の両方からこの軸を丸ごと除外する
    （frontend/src/components/Map/secondaryAxes.ts: secondaryAxesFromCatalogAxes()の
    フィルタ条件）。既定trueは既存軸の見た目を変えないための後方互換値。旧`proxy_hint`
    （専用地図レイヤーを持たない軸向けの代役案内文）は、この真偽値ON/OFFで
    「そもそも表示しない」という選択肢自体が持てるようになったことで不要となり撤去した
    （ユーザー判断2026-08-25、改善計画T318）。"""
    time_scope: Literal["always", "night_only"] = "always"
    """改善計画T352: この軸の重みが常に有効か、特定の時間帯でのみ有効かの宣言。
    従来は`road_graph_engine.py`/`openrouteservice_engine.py`のT173ロジックが
    `"night"`というaxis_idを直接分岐条件にしていた（市民薄明の外なら重みそのまま、
    日中なら0倍）。両エンジンは「`time_scope != "always"`な軸のうち、現在の
    `active_scopes`に含まれないものの重みを0倍にする」という汎用ロジックへ置き換わり、
    このフィールドが唯一の分岐条件になった（`RoutePreference.with_time_scope`、
    `domain/axis_definitions.py: time_scoped_weights`参照）。将来、別の時間帯依存軸
    （例: 通勤ラッシュ限定）を追加する場合も、このフィールドへ新しい値
    （例: "commute_only"）を1つ増やすだけでよく、エンジン側のコード変更は不要。"""
    supports_route_coloring: bool = False
    """改善計画T352: この軸のdifficulty（0-100）を、ルート地図の色分けモード
    （frontend/src/components/Map/routeStyleModes.ts）の選択肢として使えるかの宣言。
    従来は`RouteStyleModeId`が`"wind"`・`"gradient"`を固定の文字列unionとして
    ハードコードしていた。true設定の軸は`axis_difficulties[axis_id]`を値source とする
    汎用の3段階（易しい/普通/難しい）色分けモードとして自動的に選択肢へ現れる
    （`routeStyleModesFromCatalogAxes`参照）。**`gradient`はこの機構の対象外のまま
    据え置く**——gradient色分けは向き（登り/下り）を区別するため、difficulty
    （前処理でabsを取った絶対値）ではなく符号付きの生材料`gradient_percent`を直接
    読む必要があり、単純な「difficultyを3段階で塗る」という本フラグの汎用機構では
    表現できない（この非対称性は起票時点[T352]で既に想定済み、`routeStyleModes.ts`の
    コメント参照）。"""
    display_override: AxisDisplaySpec | None = None
    """地図ramp表示（domain/axis_display.py: axis_display_for()が返す値）の手書き上書き。
    未設定は`derive_ramp_inputs()`による自動導出（不可能ならkind="none"）に委ねる。
    複数材料の重み付き結合はderive_ramp_inputsが数学的に正確に自動導出できるため
    通常は不要——統計的に閾値を調整したい場合（stop_density/accident）、または他の軸を
    参照する材料構成でderive_ramp_inputsが解決できない場合（car_stress、改善計画T292の
    軸階層）にのみ設定する。軸スタジオのGUIフォーム（AxisComposer.tsx）は現時点で
    この項目の編集UIを持たない（TileInputSpecの構造が複雑なため、まずは管理API経由の
    直接編集のみ対応。GUI化は将来検討、docs/improvement-plan.md T310参照）。"""

    @property
    def materials(self) -> list[str]:
        """この軸が参照する材料id・軸idの一覧（shapeから導出。二重管理しない。
        `priority_overrides`が参照する材料も含む）。呼び出し側が材料か軸かを
        区別する必要がある場合は`material_catalog.is_known_material`で判別する
        （改善計画T292、`check_material_exclusivity`参照）。"""
        if isinstance(self.shape, BreakpointLinearShape):
            shape_materials = [term.material for term in self.shape.terms]
        elif isinstance(self.shape, CategoricalShape):
            shape_materials = [self.shape.material]
        else:
            shape_materials = [material for material, _ in self.shape.flags]
        override_materials = [cond.material for cond in self.priority_overrides]
        # 順序を安定させつつ重複を除く（同じ材料をpriority_overridesとshapeの両方が
        # 参照するケース、例: motor_vehicle_noを他のtermでも使う場合を許容するため）。
        seen: dict[str, None] = {}
        for m in [*shape_materials, *override_materials]:
            seen.setdefault(m, None)
        return list(seen)


# 改善計画T350: 14軸分のPython literalは撤去した。`axis_definitions`DBテーブルが唯一の
# 正本で、起動時（app/services/axis_registry_service.py: refresh_axis_definitions）に
# DBから読み込みこの辞書をin-placeで書き換えるまでは空のまま。新規軸の追加・既存軸の
# 変更は他のスキーマ変更と同じく手書きのmigration SQL（backend/migrations/）で行う。
AXIS_DEFINITIONS: dict[str, AxisDefinition] = {}


class AxisMaterialConflictError(ValueError):
    """新規/更新しようとした軸の材料が、既存の別軸と重複している場合に送出する
    （改善計画T268）。

    `registry.py: register_axis`の`AxisInputConflictError`（表示用レジストリの排他帰属
    チェック）と同じ「1つの材料は原則1つの軸だけが使う」原則を、実際にルーティング計算を
    駆動する`AXIS_DEFINITIONS`側（Stage DでDB化・管理API経由の書き込みが可能になった）へ
    移植したもの。軸スタジオ（T270）で任意の軸を登録できるようになる前に、既存軸が使う
    材料を新軸が黙って再利用し二重計上が混入する事故を構造的に防ぐ。
    """

    def __init__(self, axis_id: str, conflicting_axis_id: str, overlapping_materials: set[str]) -> None:
        self.axis_id = axis_id
        self.conflicting_axis_id = conflicting_axis_id
        self.overlapping_materials = overlapping_materials
        materials = ", ".join(sorted(overlapping_materials))
        super().__init__(
            f"axis '{axis_id}' shares material(s) [{materials}] with existing axis '{conflicting_axis_id}'; "
            f"each material may belong to at most one axis (exclusive assignment principle, T268)"
        )


class AxisPublishedImmutableError(ValueError):
    """公開済み（is_published=True）の軸を更新・削除しようとした場合に送出する
    （改善計画T271）。

    一般ユーザーの保存設定（RouteSettingsPanelのプリセット・重み）はaxis_idキーで
    再現されるため、公開後の破壊的変更・削除は他ユーザーの設定を黙って壊す。
    改良したい場合は複製（新しいaxis_idの下書き軸として作成）してから公開する導線を
    UI側に用意する（この関数は変更を一切拒否するのみで、複製自体は関与しない）。
    """

    def __init__(self, axis_id: str, action: str) -> None:
        self.axis_id = axis_id
        self.action = action
        super().__init__(
            f"axis '{axis_id}' is published and cannot be {action} "
            f"(publish-immutability principle, T271); duplicate it as a new draft axis instead"
        )


def check_publish_immutability(existing: AxisDefinition, action: str) -> None:
    """`existing`が公開済みなら`AxisPublishedImmutableError`を送出する（更新・削除の
    どちらの直前でも呼べる汎用関数、`action`はエラーメッセージ用の英語動詞句）。"""
    if existing.is_published:
        raise AxisPublishedImmutableError(existing.axis_id, action)


def check_material_exclusivity(candidate: AxisDefinition, existing: dict[str, AxisDefinition]) -> None:
    """`candidate`の材料が`existing`内の他軸と重複していないか検査する。

    `existing`に`candidate.axis_id`と同じキーが含まれていても（更新時、自分自身との
    比較になるため）スキップする。重複が見つかれば`AxisMaterialConflictError`を送出する
    （登録は行わない、呼び出し元の責務）。

    現時点の`AXIS_DEFINITIONS`（8軸）には`registry.py`の`shared=True`相当（距離等、
    複数軸が参照してよい共通コンテキスト）の材料が存在しないため、`shared`フラグは
    持たない。将来そうした材料が必要になった時点で`MaterialTerm`側への追加を検討する。

    改善計画T292: `candidate.materials`は材料idと軸id（軸の階層構造、他の軸への参照）を
    区別せずに返すため、`MATERIAL_CATALOG`に実在するものだけを検査対象とする
    （`is_known_material`でフィルタ）。軸参照は複数の公開軸が同じ内部軸を意図的に
    共有できる設計のため、この排他チェックの対象外——材料の二重計上とは別の話。
    """
    from app.domain.material_catalog import is_known_material

    candidate_materials = {m for m in candidate.materials if is_known_material(m)}
    for other_id, other in existing.items():
        if other_id == candidate.axis_id:
            continue
        overlap = candidate_materials & {m for m in other.materials if is_known_material(m)}
        if overlap:
            raise AxisMaterialConflictError(candidate.axis_id, other_id, overlap)


class AxisDependencyCycleError(ValueError):
    """軸間の依存関係（他の軸をmaterialとして参照する構造）に循環があった場合に
    送出する（改善計画T292）。"""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        chain = " -> ".join(cycle)
        super().__init__(f"circular axis dependency detected: {chain}")


def axis_dependencies(definition: AxisDefinition, known_axis_ids: set[str]) -> set[str]:
    """`definition`が参照する軸id（materialsのうち、材料ではなく軸を指すもの）を返す
    （改善計画T292）。`known_axis_ids`は循環検出・評価順序決定の対象となる軸id全体
    （通常は`AXIS_DEFINITIONS`のキー集合）。"""
    from app.domain.material_catalog import is_known_material

    return {m for m in definition.materials if not is_known_material(m) and m in known_axis_ids}


class AxisInternalAxisPublishError(ValueError):
    """他の軸から参照されている内部軸を公開（is_published=True）しようとした場合に
    送出する（改善計画T292/T311フォローアップ）。

    「内部軸は他の軸から参照される専用で、恒久的に非公開のまま運用する」という軸階層の
    設計意図（本モジュールのAxisDefinition docstring「軸の階層」参照）は、従来コード
    レベルで強制されていなかった。軸スタジオでの操作（動作確認・トグルの戻し忘れ等）で
    car_stress内部軸の1つがis_published=Trueのまま保存され、migration適用ラグでDB読み込み
    自体が失敗し続けていた間は気付かれず、DB読み込みが復旧した際に一般ユーザー向けの
    ルート設定画面（`GET /api/axis-catalog`、is_publishedフィルタのみ）へそのまま
    漏れ出た実障害があった（T311フォローアップ、2026-08-25）。
    """

    def __init__(self, axis_id: str, referencing_axis_id: str) -> None:
        self.axis_id = axis_id
        self.referencing_axis_id = referencing_axis_id
        super().__init__(
            f"axis '{axis_id}' is referenced by axis '{referencing_axis_id}' as an internal axis "
            f"and cannot be published (internal axes stay permanently unpublished, T292/T311)"
        )


def check_internal_axis_not_published(candidate: AxisDefinition, existing: dict[str, AxisDefinition]) -> None:
    """`candidate`が`existing`内の他の軸（自分自身を除く）から軸参照（内部軸）として
    使われているにもかかわらず、is_published=Trueで保存しようとしていないか検査する
    （改善計画T292/T311フォローアップ）。非公開のままなら常に許可する（早期return）。
    """
    if not candidate.is_published:
        return
    known_axis_ids = set(existing) | {candidate.axis_id}
    for other_id, other in existing.items():
        if other_id == candidate.axis_id:
            continue
        if candidate.axis_id in axis_dependencies(other, known_axis_ids):
            raise AxisInternalAxisPublishError(candidate.axis_id, other_id)


_TOPOLOGICAL_ORDER_CACHE_MAX_SIZE = 64
_topological_order_cache: dict[tuple[tuple[str, tuple[str, ...]], ...], list[str]] = {}


def _topological_axis_order_cache_key(
    definitions: dict[str, AxisDefinition],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((axis_id, tuple(definition.materials)) for axis_id, definition in definitions.items())


def topological_axis_order(definitions: dict[str, AxisDefinition]) -> list[str]:
    """軸を「依存先（参照される軸）が先」の順序に並べ替える（改善計画T292、
    深さ優先探索によるトポロジカルソート）。循環参照があれば`AxisDependencyCycleError`を
    送出する。依存を持たない軸同士の相対順序は`definitions`の挿入順を保つ（既存の
    Neumaier加算のビット一致要件——3次合成の対象は公開軸のみだが、軸単位のdifficulty
    計算自体の再現性のため安定ソートにする）。

    コードレビュー指摘の修正: `compute_edge_axis_scores`等がEdge単位（1ルート候補あたり
    最大数百回）で呼ぶホットパスのため、結果をプロセス内メモリでメモ化する。キーは
    各軸の`materials`（依存関係を決める唯一の入力）から導出した内容ベースの値であり、
    `AXIS_DEFINITIONS`自体のオブジェクト同一性には依存しない（`refresh_axis_definitions`
    [services/axis_registry_service.py]が`AXIS_DEFINITIONS.clear()`+`update()`で同一
    オブジェクトのまま中身だけ差し替えるため、オブジェクトidベースのキーだと差し替え後も
    古いキャッシュを誤って返しうる）。循環参照（`AxisDependencyCycleError`）はキャッシュ
    しない（軸スタジオでの試行錯誤中に一時的な循環を経て修正された場合の再評価を妨げない
    ため）。キャッシュは単純なFIFOで上限を設け、無制限な増大を避ける
    （`AxisRegistryAdminService`は呼び出しのたびに新しい`dict`を作るため、通常運用では
    ほぼ`AXIS_DEFINITIONS`本体のキーだけがヒットし続ける）。
    """
    cache_key = _topological_axis_order_cache_key(definitions)
    cached = _topological_order_cache.get(cache_key)
    if cached is not None:
        return cached

    known_axis_ids = set(definitions.keys())
    order: list[str] = []
    visited: dict[str, int] = {}  # 0=visiting, 1=done

    def visit(axis_id: str, path: list[str]) -> None:
        state = visited.get(axis_id)
        if state == 1:
            return
        if state == 0:
            raise AxisDependencyCycleError([*path, axis_id])
        visited[axis_id] = 0
        for dep in sorted(axis_dependencies(definitions[axis_id], known_axis_ids)):
            visit(dep, [*path, axis_id])
        visited[axis_id] = 1
        order.append(axis_id)

    for axis_id in definitions:
        visit(axis_id, [])

    if len(_topological_order_cache) >= _TOPOLOGICAL_ORDER_CACHE_MAX_SIZE:
        _topological_order_cache.pop(next(iter(_topological_order_cache)))
    _topological_order_cache[cache_key] = order
    return order


def default_axis_weights() -> dict[str, float]:
    """axis_idキーの既定重み辞書（APIで上書きされる前の値、`RoutePreference`の
    既定値・`GET /api/axis-catalog`のpreference_defaultsが共通で参照する単一
    ソース、改善計画T316）。

    改善計画T292: 内部軸（`is_published=False`）は一般ユーザーの重み付け対象外のため
    除外する。`RoutePreference`のバリデーション（未知のaxis_idを拒否）もこの集合と
    整合させる。"""
    return {
        axis_id: definition.default_weight
        for axis_id, definition in AXIS_DEFINITIONS.items()
        if definition.is_published
    }


def time_scoped_weights(weights: Mapping[str, float], active_scopes: frozenset[str]) -> dict[str, float]:
    """`weights`のうち、`time_scope`が"always"以外（AXIS_DEFINITIONS参照）かつ
    `active_scopes`に含まれない軸の重みを0.0にした新しい辞書を返す（改善計画T352、
    元のT173 night動的化ロジックの汎用化。`weights`自体は変更しない）。

    従来は`road_graph_engine.py`/`openrouteservice_engine.py`が`"night"`という
    axis_idを直接分岐条件にしていたが、`AxisDefinition.time_scope`という性質ベースの
    宣言的フィールドを持つことで、エンジン側は「この性質を持つ軸を探して掛け替える」
    という汎用ロジックだけを持てばよくなった。将来別の時間帯依存軸を追加する際も、
    その軸のtime_scopeを設定するだけでよく、エンジン側のコード変更は不要。

    `weights`に無いaxis_id（内部軸への重み・非公開化された軸等）は無視する
    （`RoutePreference.with_weight`の「対象軸が存在しなければ無変更」という既定動作、
    改善計画T316フォローアップと同じ理由）。"""
    overrides = {
        axis_id: 0.0
        for axis_id, definition in AXIS_DEFINITIONS.items()
        if axis_id in weights and definition.time_scope != "always" and definition.time_scope not in active_scopes
    }
    if not overrides:
        return dict(weights)
    return {**weights, **overrides}


def car_stress_display_level(difficulty: float | None) -> int | None:
    """car_stress軸のdifficulty(0-100)を表示用の1-5生値へ逆変換する
    （RouteSegmentDetail.car_stress、road_graph_engine.py/openrouteservice_engine.pyが
    共通で使う。改善計画T292のコードレビュー指摘の修正: 逆変換式が両エンジンへ
    (level-1)/4*100の逆算として重複ハードコードされていたのを1箇所へ集約）。

    breakpointsをここへ再度ハードコードせず`AXIS_DEFINITIONS["car_stress"]`から動的に
    読むため、旧clamp_level(.,1,5)相当のこの軸のbreakpointsが将来変わっても追従不要。
    Python組み込みround()は偶数への銀行丸め（例: difficulty=37.5だとlevel=2.5→2に丸まり、
    difficulty=62.5だとlevel=3.5→4に丸まるという非対称な挙動）のため、四捨五入
    （0.5は常に切り上げ）で境界を一貫させるmath.floor(x+0.5)を使う。

    改善計画T320: 「1-5の順序尺度への逆変換」はBreakpointLinearShape（連続値の折れ点補間）
    という形状を前提にしている。以前は`AXIS_DEFINITIONS["car_stress"]`の`shape`がこの型で
    あることをassertで前提していたため、運用者が軸スタジオでcar_stressの評価式を
    BreakpointLinearShape以外（categorical等）へ作り替えると、逆変換の前提自体が崩れ
    AssertionErrorがルート生成のたびに500として表面化していた。この逆変換が意味を
    持たない形状へ変わった場合は「表示用の生値を算出できない」というNone（データ無し）
    として安全側に倒す（他のdifficulty系関数と同じ「算出不能はNone」の規約）。
    """
    if difficulty is None:
        return None
    shape = AXIS_DEFINITIONS["car_stress"].shape
    if not isinstance(shape, BreakpointLinearShape):
        return None
    (x0, y0), (x1, y1) = shape.breakpoints[0], shape.breakpoints[-1]
    clamped = min(max(difficulty, y0), y1)
    level = x0 + (clamped - y0) / (y1 - y0) * (x1 - x0)
    return math.floor(level + 0.5)


def _priority_override_matches_scalar(value: object, equals: str) -> bool:
    """スカラー材料値がPriorityCondition.equals（str固定）と一致するか判定する。

    bool材料（`materials`に生のPython bool値がそのまま入る、例: motor_vehicle_no）は
    `True == "True"`が常にFalseになるため、"true"/"false"（大文字小文字を無視）の
    文字列表現へ正規化して比較する。categorical材料（str値）はそのまま比較する。
    """
    if isinstance(value, bool):
        return equals.strip().lower() == str(value).lower()
    return value == equals


def evaluate_axis_scalar(definition: AxisDefinition, materials: Mapping[str, object]) -> float | None:
    """1Edge/1区間分の材料値から軸別difficultyを算出する（欠損=None）。

    `materials`は材料id→解決済みスカラー値（float/bool/int/None）。定義が参照しない
    材料が含まれていてもよい（呼び出し元は既知の全材料をまとめて渡してよい）。

    改善計画T292: `definition.priority_overrides`が1件でも一致すれば、shapeの通常計算を
    スキップしその条件のvalueをそのまま返す（定義順で最初に一致したものを採用。探索除外の
    ハードフィルタとは別に「評価を優先確定する」ための機構、最初の適用例はmotor_vehicle_no
    =true。自転車通行禁止は既存の0次ハードフィルタ`no_bicycle`で既にカバー済みのため
    この機構は使わない）。
    """
    for override in definition.priority_overrides:
        if _priority_override_matches_scalar(materials.get(override.material), override.equals):
            return override.value
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape):
        total: float | None = None
        for term in shape.terms:
            value = materials.get(term.material)
            if value is None:
                if term.required:
                    return None
                continue
            contribution = value * term.weight
            total = contribution if total is None else total + contribution
        if total is None:
            return None
        if shape.preprocess == "abs":
            total = abs(total)
        return round(evaluate_breakpoint_linear(total, shape.breakpoints), 1)
    if isinstance(shape, CategoricalShape):
        value = materials.get(shape.material)
        if value is None:
            return None
        return evaluate_categorical(value, shape.mapping)
    # FlagSumShape
    flag_values = []
    for material, points in shape.flags:
        value = materials.get(material)
        if value is None:
            return None
        flag_values.append((value, points))
    return evaluate_flag_sum(flag_values, cap=shape.cap)


def evaluate_axes_scalar(materials: Mapping[str, object]) -> tuple[dict[str, float | None], dict[str, object]]:
    """`AXIS_DEFINITIONS`の全軸を依存順（内部軸→公開軸）で評価する共通ループ
    （コードレビュー指摘の修正: 同じ「`topological_axis_order`で依存順に並べ、
    `evaluate_axis_scalar`の結果を次の軸のmaterialとして混ぜ込みながら進め、公開軸だけを
    返す」という組み立てが`compute_edge_axis_scores`/`axis_inspector_breakdown`
    [domain/evaluation.py]・`evaluate_axis_difficulties`[domain/difficulty.py]の3箇所に
    重複していたための共通化）。

    戻り値は`(公開軸のみのdifficulty辞書, 評価済みの内部軸も含む全materials辞書)`。
    前者は内部軸（`is_published=False`）を含まないが、値が算出不能だった公開軸は
    `None`のままキーを残す（`axis_inspector_breakdown`の`available=False`判定・
    `evaluate_axis_difficulties`の`composite_difficulty`への受け渡しがこれを前提にする
    ため、値がNoneのキーを黙って落とさない）。呼び出し元でNoneのキー自体を除きたい場合は
    呼び出し側でフィルタする（`compute_edge_axis_scores`参照）。
    """
    scores: dict[str, float | None] = {}
    materials_with_axes: dict[str, object] = dict(materials)
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        value = evaluate_axis_scalar(definition, materials_with_axes)
        if definition.is_published:
            scores[axis_id] = value
        if value is not None:
            materials_with_axes[axis_id] = value
    return scores, materials_with_axes


def evaluate_axis_array(definition: AxisDefinition, materials: Mapping[str, np.ndarray]) -> np.ndarray:
    """`evaluate_axis_scalar`の配列版（欠損=NaN、`compute_edge_costs_bulk`のベクトル化経路用）。

    `materials`は材料id→同一形状のnumpy配列（フラグ材料はbool配列、それ以外はfloat配列で
    欠損はNaN。categorical材料はdtype=object の文字列配列）。requiredな材料のNaNは演算で
    自然に伝播し、required=Falseの材料のNaNは0へ置き換えて寄与なしとして扱う（スカラー版の
    None規約と対応）。

    改善計画T292: `definition.priority_overrides`はshape計算の結果へ後から重ねる
    （`np.where`をpriority_overridesの逆順に重ねることで、先頭の条件が最終的に最優先になる
    ——スカラー版の「定義順で最初に一致したものを採用」と同じ優先順位）。
    """
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape):
        total: np.ndarray | None = None
        for term in shape.terms:
            values = materials[term.material]
            if not term.required:
                values = np.where(np.isnan(values), 0.0, values)
            contribution = values * term.weight
            total = contribution if total is None else total + contribution
        assert total is not None  # 定義上termsは1件以上
        if shape.preprocess == "abs":
            total = np.abs(total)
        result = np.round(evaluate_breakpoint_linear(total, shape.breakpoints), 1)
    elif isinstance(shape, CategoricalShape):
        # コードレビュー指摘の修正: `evaluate_categorical`は`values == key`という
        # 要素ごとの比較のみでbool配列・str(dtype=object)配列のどちらも正しく動く
        # （`bool配列 == True/False`は`bool配列 == 1.0/0.0`と同じ結果になる、実データ
        # 検証済み）ため、bool材料をfloatキーへ変換する特別扱いは不要だった。
        result = evaluate_categorical(materials[shape.material], shape.mapping)
    else:
        # FlagSumShape
        result = evaluate_flag_sum(
            [(materials[material], points) for material, points in shape.flags], cap=shape.cap
        )
    for override in reversed(definition.priority_overrides):
        values = materials[override.material]
        # bool配列（フラグ材料、例: motor_vehicle_no）は"true"/"false"の文字列表現へ
        # 正規化して比較する（スカラー版_priority_override_matches_scalarと同じ理由:
        # bool配列とstr型のequalsをそのまま==比較すると常にFalseになる）。
        mask = values == (override.equals.strip().lower() == "true") if values.dtype == bool else values == override.equals
        result = np.where(mask, override.value, result)
    return result
