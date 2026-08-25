"""評価軸の定義データと汎用評価関数（改善計画T221 Stage B/C、ADR: docs/decisions/t221-axis-registry.md）。

現行7軸（勾配・向かい風・舗装質・停止密度・車ストレス・事故密度・夜間）の
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
- Stage D（DBテーブル化）・Stage E（GUI編集）は製品判断待ちのため未実装
  （ADR「スコープ外・要検討事項」参照）。それまでの間、本モジュールが
  「Pythonファイルのままのレジストリ」（Stage C）として評価ロジックの参照元になる。

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
from app.domain.registry import AxisDisplaySpec, TileInputSpec

# 改善計画T149（設計プロンプト改訂2026-08-18「現行9軸からの帰属先」）: 交差点密度は
# 単独軸を持たず、タグなし交差点(次数3以上のroad_node、信号等のタグが付いていない
# もの)として、信号・横断歩道・一時停止・踏切と同じstop_density軸へ低い重みで吸収する。
# 重みはsignal等のstop_poi(重み1.0相当)に対する相対値。値の経緯はdomain/difficulty.pyの
# 旧定義コメント（T149）参照。stop_density軸のMaterialTermとタイル表示宣言
# （registry_defaults.pyのtile_inputs）の両方がこの定数を参照する。
UNSIGNALED_INTERSECTION_WEIGHT = 0.3


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
    str（highway/bicycle_infra等、MATERIAL_CATALOGのdtype="categorical"材料、
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
    proxy_hint: str | None = None
    """display.kind="none"（専用地図レイヤー無し）の軸向け、代役レイヤーへの案内文。
    未設定は案内なし（無効化されたチップとしてのみ表示）。"""
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


# 7軸の定義。**辞書の挿入順は合成（composite）の加算順として意味を持つ**
# （スカラー版`composite_difficulty`のPython `sum()`と配列版`_neumaier_accumulate`の
# 浮動小数点結果をビット単位で一致させるには加算順が同一である必要がある。
# `tests/test_evaluation_bulk.py`が全Edge一致で検証する）。
#
# 各パラメータの根拠・暫定値の経緯（P2据え置き等）はgit履歴（domain/difficulty.py・
# domain/night.pyの旧定数定義、T239以前）参照。
#
# car_stress内部軸5つのマッピング/breakpointsを、地図表示（display_override.tile_inputs、
# car_stress公開軸のエントリ参照）と評価shape（各内部軸のエントリ）の両方から参照する
# 単一ソースとして先出しする（改善計画T310。以前はaxis_display.pyが評価済みの
# AXIS_DEFINITIONS[...]を事後的に読んで複製を避けていたが、display_overrideを軸自身の
# フィールドへ変えたことで、AXIS_DEFINITIONS辞書リテラルの構築中に自分自身を参照できない
# ため、この形で単一ソースを保つ）。
_CAR_STRESS_HIGHWAY_BASE_MAPPING: dict[str, float] = {
    "cycleway": 1.0,
    "living_street": 1.0,
    "residential": 2.0,
    "unclassified": 2.0,
    "track": 2.0,
    "tertiary": 3.0,
    "tertiary_link": 3.0,
    "secondary": 3.0,
    "secondary_link": 3.0,
    "primary": 4.0,
    "primary_link": 4.0,
    "trunk": 4.0,
    "trunk_link": 4.0,
}
_CAR_STRESS_BICYCLE_INFRA_MAPPING: dict[str, float] = {
    "separated": -2.0,
    "lane": -1.0,
    "shared_busway": 0.0,
    "shared_pedestrian": 0.0,
    "roadway": 1.0,
}
_CAR_STRESS_MAXSPEED_BREAKPOINTS: list[tuple[float, float]] = [
    (0.0, -1.0),
    (30.0, -1.0),
    (31.0, 0.0),
    (59.0, 0.0),
    (60.0, 1.0),
    (999.0, 1.0),
]
_CAR_STRESS_LANES_BREAKPOINTS: list[tuple[float, float]] = [
    (0.0, -1.0),
    (1.0, -1.0),
    (2.0, 0.0),
    (3.0, 0.0),
    (4.0, 1.0),
    (99.0, 1.0),
]
_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING: dict[bool, float] = {True: -1000.0, False: 0.0}

AXIS_DEFINITIONS: dict[str, AxisDefinition] = {
    # 勾配。材料gradient_percent=Edge単位の平均勾配%（ElevationAttribute.average_grade、
    # 符号付き）。絶対値をとり0-3%易しい/3-6%普通/6-9%大変/9%以上激坂の目安で変換する。
    "gradient": AxisDefinition(
        axis_id="gradient",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (3.0, 25.0), (6.0, 50.0), (9.0, 75.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="勾配",
        description="登り坂の急さが小さいほど易しい",
        category="観測",
        is_published=True,
        icon_id="incline",
        chip_label="勾配",
        proxy_hint="（地図表示なし）標高レイヤーで確認できます",
    ),
    # 向かい風。材料wind_penalty=符号付き風ペナルティm/s（正=向かい風、負=追い風。
    # domain/evaluation.py: compute_wind_penalty）。追い風・無風は0、8m/sで100。
    "wind": AxisDefinition(
        axis_id="wind",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_penalty")],
            breakpoints=[(0.0, 0.0), (8.0, 100.0)],
        ),
        default_weight=0.26,
        label="風",
        description="向かい風が弱いほど易しい",
        category="動的",
        is_published=True,
    ),
    # 舗装質。材料surface_good=舗装良否（domain/road.py: classify_osm_surfaceの3値、
    # True/False/欠損）。舗装路は0、非舗装は80。
    "surface_q": AxisDefinition(
        axis_id="surface_q",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.19,
        label="舗装質",
        description="舗装路であるほど易しい",
        category="観測",
        is_published=True,
        icon_id="wave",
        chip_label="舗装",
    ),
    # 停止密度。材料stop_count_per_km=信号・横断歩道・一時停止・踏切の合計密度(回/km、必須)、
    # intersection_count_per_km=タグなし交差点密度(回/km、補助・欠損は寄与0)。
    # 合算値0回/kmで0、4回/km(250mに1回)で100。
    "stop_density": AxisDefinition(
        axis_id="stop_density",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="stop_count_per_km"),
                MaterialTerm(
                    material="intersection_count_per_km",
                    weight=UNSIGNALED_INTERSECTION_WEIGHT,
                    required=False,
                ),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.20,
        label="停止密度",
        description="信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい",
        category="観測",
        is_published=True,
        icon_id="density-stack",
        chip_label="停止密度",
        panel_hint="信号・横断歩道・一時停止・踏切等の停止要因が、沿線でどれだけ密集しているかの目安です。"
        "実際の位置は「停止要因」レイヤーで確認できます。",
        # 改善計画T310: 以前はaxis_display.py: STOP_DENSITY_DISPLAY（軸id→値のハードコード
        # 辞書）だったものを、軸自身のフィールドへ移設した（他の既存軸限定の特別扱いと同じ
        # 理由で特別扱いを解消。docs/improvement-plan.md T310参照）。derive_ramp_inputsは
        # 技術的にはこの軸も自動導出できるが、既存thresholds[1,2,4]は統計的経験則で単純な
        # 折れ点流用（自動導出だと[4.0]の1閾値のみ）より段階が細かいため、意図的に手書きの
        # まま維持する（domain/axis_display.pyのモジュールdocstring参照）。
        display_override=AxisDisplaySpec(
            kind="ramp",
            label="停止密度",
            category="trafficSafety",
            tile_inputs=[
                TileInputSpec(property="stop_per_km", weight=1.0),
                TileInputSpec(property="intersection_per_km", weight=UNSIGNALED_INTERSECTION_WEIGHT),
            ],
            thresholds=[1.0, 2.0, 4.0],
            unit="回/km",
            note="信号・横断歩道・一時停止・踏切に無タグ交差点（重み0.3）を加えた"
            "停止要因の密度。way単位の事前集計（way_attribute_counts）由来",
        ),
    ),
    # 車ストレス（改善計画T292: 専用Pythonレシピ[旧domain/traffic.py: car_stress_level、
    # CarStressRecipe等]を廃止し、内部軸5つ+公開軸1つの階層構造で再現する）。
    #
    # 内部軸（is_published=False、他の公開軸から参照される専用の推定軸。単独では
    # 一般ユーザーに公開しない）。各軸の値は「highway基準値(1-4)に対する加減点」という
    # 共通のスケールに揃えてあり、公開軸car_stress側でそのまま合算する。
    #
    # highway基準値（旧ROAD_SUITABILITY_BASE_BY_HIGHWAY、12区分、値は完全に同一）。
    # 未登録のhighway（footway/path等の歩行者共用道、実データで実在——dev DB実測で
    # motor_vehicle=noタグの81.6%がこれに該当）は評価しない（CategoricalShapeの
    # 既定挙動どおりNone）。car_stress公開軸側でrequired=Trueにすることで、旧ロジックの
    # 「highway未登録なら car_stress全体を評価しない」を再現する。
    "car_stress_highway_base": AxisDefinition(
        axis_id="car_stress_highway_base",
        shape=CategoricalShape(material="highway", mapping=_CAR_STRESS_HIGHWAY_BASE_MAPPING),
        default_weight=0.0,
        label="車ストレス内部軸: highway基準値",
        description="highway種別による車の圧迫感の基準値(1-4、非公開)",
        category="推定",
        is_published=False,
    ),
    # 自転車インフラ由来の補正（改善計画T291で承認済みのスコアを流用、旧cycleway_class
    # [3値]をbicycle_infra[6値、domain/traffic.py: classify_bicycle_infrastructure]へ
    # 精密化）。0-100スケールのユーザー承認値（separated=0/lane=20/shared_busway=40/
    # shared_pedestrian=50/roadway=70）を`round(score/100*4-2)`でhighway基準値と同じ
    # 加減点スケールへ変換した値をそのままmappingへ記録する
    # （separated=-2[旧track相当、変更なし]/lane=-1[変更なし]/shared_busway=0[旧-1から変更]/
    # shared_pedestrian=0[新規]/roadway=+1[新規]）。shared_buswayの挙動変化はユーザーが
    # 意図して求めた再定義（T291合意事項）。prohibitedは0次ハードフィルタ(no_bicycle)で
    # 通常除外されるため補正を持たない（未登録→補正なし0点、旧ロジックと同じ扱い）。
    "car_stress_bicycle_infra_adjustment": AxisDefinition(
        axis_id="car_stress_bicycle_infra_adjustment",
        shape=CategoricalShape(material="bicycle_infra", mapping=_CAR_STRESS_BICYCLE_INFRA_MAPPING),
        default_weight=0.0,
        label="車ストレス内部軸: 自転車インフラ補正",
        description="自転車インフラ種別による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    # 制限速度による補正（低速緩和-1・高速加点+1、旧MotorVehicleDensityRecipeの既定値と
    # 同一）。breakpointsは閾値ちょうどの整数(maxspeed_kmhは常に整数、domain/recipe.py:
    # parse_maxspeed)で段差を表現する（30以下→-1、31-59→0、60以上→+1）。
    "car_stress_maxspeed_adjustment": AxisDefinition(
        axis_id="car_stress_maxspeed_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="maxspeed_kmh")],
            breakpoints=_CAR_STRESS_MAXSPEED_BREAKPOINTS,
        ),
        default_weight=0.0,
        label="車ストレス内部軸: 制限速度補正",
        description="制限速度による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    # 車線数による補正（少車線緩和-1・多車線加点+1、旧CarStressRecipe/
    # MotorVehicleDensityRecipeの既定値と同一）。改善計画T292演算要素⑥
    # （自転車専用道路区間でのlanes低減緩和の抑制）は実データ確認（dev DB
    # 2026-08-19、該当ほぼ皆無）によりユーザー承認済みで単純化し、常に適用する
    # （bicycle_infraによる条件分岐を持たない）。lanes_countは常に整数
    # （domain/recipe.py: parse_lanes）のためbreakpointsで段差を表現できる
    # （1以下→-1、2-3→0、4以上→+1）。
    "car_stress_lanes_adjustment": AxisDefinition(
        axis_id="car_stress_lanes_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="lanes_count")],
            breakpoints=_CAR_STRESS_LANES_BREAKPOINTS,
        ),
        default_weight=0.0,
        label="車ストレス内部軸: 車線数補正",
        description="車線数による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    # 指定路線（KSJ N10/N12）該当による加点（+1、種別[emergency_transport/
    # critical_logistics]によらず一律。material_catalog.py: is_designatedのdocstring
    # 参照——種別を評価まで運ぶ配線が無いための簡略化）。
    "car_stress_designation_adjustment": AxisDefinition(
        axis_id="car_stress_designation_adjustment",
        shape=CategoricalShape(material="is_designated", mapping={True: 1.0, False: 0.0}),
        default_weight=0.0,
        label="車ストレス内部軸: 指定路線補正",
        description="指定路線(緊急輸送道路・重要物流道路)該当による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    # motor_vehicle=no（自動車通行不可）の優先確定（旧ロジック: 他の補正に関わらず
    # レベル1固定）。改善計画T292検討時、shape評価を無条件スキップするpriority_overrides
    # 機構を最初はこの用途に想定していたが、実データ確認でmotor_vehicle=noの81.6%が
    # highway基準値未登録（footway/path）であることが判明し、priority_overridesを
    # car_stress公開軸へ直接使うとhighway未登録の場合まで車ストレス最良値が確定して
    # しまう（旧ロジック=未評価のまま、と不一致）という問題が見つかった。そこで
    # priority_overridesではなく、他の全補正の取りうる最大合計(highway基準値4+
    # bicycle_infra補正+1+maxspeed補正+1+lanes補正+1+designation補正+1=8)を確実に
    # 下回る大きさの固定マイナス項(-1000、安全マージン込み)を「普通の内部軸」として
    # 加算する方式にした。breakpoints両端のクランプ（np.interp既定挙動）により
    # motor_vehicle_no=trueの区間は必ず最良値(0)へ張り付く。highway基準値が未登録
    # （required=True）なら、この補正が効いていても公開軸全体がNoneのままになり
    # 旧ロジックと完全に一致する。**この値を変更する場合、他の内部軸の点数レンジの
    # 合計を必ず上回る負の大きさを維持すること**（軸スタジオ等でこの値だけ調整すると、
    # 他の内部軸の点数レンジ次第で頭打ちが効かなくなりうる、レビュー時要確認）。
    "car_stress_motor_vehicle_no_adjustment": AxisDefinition(
        axis_id="car_stress_motor_vehicle_no_adjustment",
        shape=CategoricalShape(material="motor_vehicle_no", mapping=_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING),
        default_weight=0.0,
        label="車ストレス内部軸: 自動車通行不可の優先確定",
        description="motor_vehicle=noの区間を最良値へ強制する内部軸(非公開)",
        category="推定",
        is_published=False,
    ),
    # 公開軸: 上記6内部軸をhighway基準値(必須)+5つの補正(任意、欠損時は補正なし=0点
    # 扱い)として加重合成する。breakpoints(1,0)-(5,100)は旧ロジックのclamp_level(.,1,5)
    # →(level-1)/4*100と同じ役割（np.interp既定のクランプ挙動で1未満/5超も1/5に丸め込む）。
    "car_stress": AxisDefinition(
        axis_id="car_stress",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="car_stress_highway_base", required=True),
                MaterialTerm(material="car_stress_bicycle_infra_adjustment", required=False),
                MaterialTerm(material="car_stress_maxspeed_adjustment", required=False),
                MaterialTerm(material="car_stress_lanes_adjustment", required=False),
                MaterialTerm(material="car_stress_designation_adjustment", required=False),
                MaterialTerm(material="car_stress_motor_vehicle_no_adjustment", required=False),
            ],
            breakpoints=[(1.0, 0.0), (5.0, 100.0)],
        ),
        default_weight=0.20,
        label="車の圧迫感",
        description="推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)",
        category="推定",
        is_published=True,
        icon_id="warning-triangle",
        chip_label="圧迫感",
        panel_hint="道路種別・自転車インフラ・制限速度・車線数・指定路線・自動車通行可否から推定した"
        "車の圧迫感の目安です。実際の交通量そのものは加味していません。内訳は区間をクリックして"
        "確認できます。",
        # 改善計画T310: 以前はaxis_display.py: CAR_STRESS_DISPLAY（軸id→値のハードコード辞書）
        # だったものを、軸自身のフィールドへ移設した（他の既存軸限定の特別扱いと同じ理由で
        # 特別扱いを解消。docs/improvement-plan.md T310参照）。derive_ramp_inputsの自動導出は
        # 「他の軸を参照するBreakpointLinearShape（このcar_stress自身のterms）」を解決できない
        # ため対象外のまま（domain/axis_display.pyのモジュールdocstring参照）、
        # stop_density/accidentと同じ前例で手書き設定する。
        display_override=AxisDisplaySpec(
            kind="ramp",
            label="車の圧迫感",
            category="trafficSafety",
            # 値はAXIS_DEFINITIONS内部軸の生の合計（0-100への最終rescale[breakpoints=(1,0)-
            # (5,100)]は適用しない）。stop_density/accidentも生の集計値へ直接thresholdsを
            # 置いており、rampの目的は色分けの相対比較であって難易度の絶対値表示ではない
            # （正確な合成コストは区間インスペクタ/api/region/axis-inspectorが
            # サーバー側で正確に計算する）。
            tile_inputs=[
                TileInputSpec(
                    property="highway",
                    categories=_CAR_STRESS_HIGHWAY_BASE_MAPPING,
                    has_unknown_fallback=True,
                ),
                TileInputSpec(
                    property="bicycle_infra",
                    categories=_CAR_STRESS_BICYCLE_INFRA_MAPPING,
                ),
                TileInputSpec(
                    property="maxspeed_kmh",
                    breakpoints=_CAR_STRESS_MAXSPEED_BREAKPOINTS,
                ),
                TileInputSpec(
                    property="lanes_count",
                    breakpoints=_CAR_STRESS_LANES_BREAKPOINTS,
                ),
                TileInputSpec(
                    # designationはcar_stress内部軸の材料(is_designated、bool)とは別の
                    # 材料（3値文字列、種別によらず一律+1）のため単一ソース化できない。
                    property="designation",
                    categories={"emergency_transport": 1.0, "critical_logistics": 1.0, "both": 1.0},
                ),
                TileInputSpec(
                    property="motor_vehicle_no",
                    boolean=True,
                    true_value=_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING[True],
                    false_value=_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING[False],
                ),
            ],
            # highway基準値（1-4）の区分境界そのもの（4段階の主要因）。他5補正の
            # 寄与幅（各-2〜+1）に対し、highway基準値が主要な分散要因のため、その
            # 境界をそのまま閾値に流用する（stop_density/accidentと同じく統計分析
            # ではなくドメイン知識による選定、実データでの分布確認は必要になれば
            # 別タスクで実施）。
            thresholds=[2.0, 3.0, 4.0],
            note="改善計画T292: highway/bicycle_infra/maxspeed_kmh/lanes_count/"
            "designation/motor_vehicle_noの6材料から自動計算する。以前は専用の"
            "手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への"
            "階層再構成でtile_inputsの重み付き結合として表現できるようになった",
        ),
    ),
    # 事故密度。材料accident_count_per_km_year=事故密度(件/(km・年)、警察庁統計の
    # 距離・収録年数正規化値)。0で0、0.5件/(km・年)で100。
    "accident": AxisDefinition(
        axis_id="accident",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="accident_count_per_km_year")],
            breakpoints=[(0.0, 0.0), (0.5, 100.0)],
        ),
        default_weight=0.08,
        label="事故密度",
        description="事故密度(件/(km・年)、警察庁統計)が低いほど易しい",
        category="推定",
        is_published=True,
        icon_id="density-scatter",
        chip_label="事故密度",
        panel_hint="警察庁の交通事故統計をもとに、自転車関連事故が沿線でどれだけ近くに集中しているかの"
        "目安です[死亡事故は重めに算入]。実際の発生地点は「事故」レイヤーで確認できます。",
        # 改善計画T310: 以前はaxis_display.py: ACCIDENT_DISPLAY（軸id→値のハードコード辞書）
        # だったものを、軸自身のフィールドへ移設した（stop_densityと同じ理由）。材料が年正規化
        # 済みでタイル生値とスケールが異なり、静的な変換係数を持てないためderive_ramp_inputsの
        # 自動導出対象外のまま（domain/axis_display.pyのモジュールdocstring参照）。
        display_override=AxisDisplaySpec(
            kind="ramp",
            label="事故密度",
            category="trafficSafety",
            tile_inputs=[TileInputSpec(property="accident_per_km", weight=1.0)],
            thresholds=[0.4, 0.8, 1.5],
            unit="件/km",
            note="警察庁統計（収録全年分、死亡事故は重み付き）の自転車関連事故の"
            "距離正規化密度。way単位の事前集計（way_attribute_counts）由来。"
            "正確な事故地点は既存の事故レイヤー（accidents、生の点表示）で確認できる",
        ),
    ),
    # 夜間。材料no_lit=街灯なし（litタグ不在は街灯なしとみなす安全側の判断、
    # domain/night.py参照）、has_tunnel=トンネル。各50点加算、上限100。既定重み0で運用。
    "night": AxisDefinition(
        axis_id="night",
        shape=FlagSumShape(flags=[("no_lit", 50.0), ("has_tunnel", 50.0)], cap=100.0),
        default_weight=0.0,
        label="夜間",
        description="街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)",
        category="観測",
        is_published=True,
        icon_id="crescent-moon",
        chip_label="夜間",
    ),
}


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

    現時点の`AXIS_DEFINITIONS`（7軸）には`registry.py`の`shared=True`相当（距離等、
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
