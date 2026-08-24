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

from typing import Literal, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.domain.axis_templates import (
    evaluate_breakpoint_linear,
    evaluate_categorical,
    evaluate_flag_sum,
)

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
    """カテゴリ値→定数のマッピング（丸めなし。mappingの値がそのままスコアになる）。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["categorical"] = "categorical"
    material: str
    mapping: dict[bool, float]


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

    `default_weight`はroute_preference.yaml・APIリクエストで上書きされなかった場合の
    既定の合成重み（`RoutePreference`の既定値の単一ソース）。

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
    ),
    # 車ストレス。材料car_stress_level=レシピ判定済みレベル1-5（domain/traffic.py:
    # car_stress_level。highway基準値＋cycleway/maxspeed/lanes/指定路線補正、
    # motor_vehicle=noは1固定）。レベル1で0、5で100。
    "car_stress": AxisDefinition(
        axis_id="car_stress",
        shape=BreakpointLinearShape(
            kind="recipe_then_breakpoint_linear",
            terms=[MaterialTerm(material="car_stress_level")],
            breakpoints=[(1.0, 0.0), (5.0, 100.0)],
        ),
        default_weight=0.20,
        label="車の圧迫感",
        description="推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)",
        category="推定",
        is_published=True,
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


def topological_axis_order(definitions: dict[str, AxisDefinition]) -> list[str]:
    """軸を「依存先（参照される軸）が先」の順序に並べ替える（改善計画T292、
    深さ優先探索によるトポロジカルソート）。循環参照があれば`AxisDependencyCycleError`を
    送出する。依存を持たない軸同士の相対順序は`definitions`の挿入順を保つ（既存の
    Neumaier加算のビット一致要件——3次合成の対象は公開軸のみだが、軸単位のdifficulty
    計算自体の再現性のため安定ソートにする）。
    """
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
    return order


def default_axis_weights() -> dict[str, float]:
    """axis_idキーの既定重み辞書（route_preference.yaml・APIで上書きされる前の値）。

    改善計画T292: 内部軸（`is_published=False`）は一般ユーザーの重み付け対象外のため
    除外する。`RoutePreference`のバリデーション（未知のaxis_idを拒否）もこの集合と
    整合させる。"""
    return {
        axis_id: definition.default_weight
        for axis_id, definition in AXIS_DEFINITIONS.items()
        if definition.is_published
    }


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
        # スカラー定義のboolキーを配列表現（True→1.0/False→0.0の3値float配列）へ読み替える。
        array_mapping = {float(key): score for key, score in shape.mapping.items()}
        result = evaluate_categorical(materials[shape.material], array_mapping)
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
