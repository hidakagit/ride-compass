"""評価軸の定義データと汎用評価関数（ADR: docs/records/decisions/t221-axis-registry.md）。

「一次属性由来の材料 → 軸別difficulty(0-100)」変換を、コード（軸ごとの関数）ではなく
**データ（`AXIS_DEFINITIONS`）**として宣言する。変換の計算自体は2テンプレート
（`domain/axis_templates.py`）が担い、本モジュールは「どの材料を・どのテンプレートに・
どのパラメータで通すか」だけを持つ。

- 既存テンプレート＋既存材料の組み合わせで表現できる新しい軸は、`AXIS_DEFINITIONS`へ
  1エントリ追加するだけで、区間インスペクタ・地図の値配信・ルート選び
  （`build_static_edge_score_matrix`）のすべてへ同時に反映される。評価は
  `evaluate_axis_array`1本で、Pythonの値で持つ入口（`evaluate_axis_values`）も配列にして通す。
- 材料（material）はOSM生タグそのものではなく「評価直前まで解決済みの値」
  （勾配%・風ペナルティm/s・路面の見込み・km正規化済み密度・レシピ計算済みレベル・
  タグ由来フラグ）。材料の解決（抽出）は呼び出し元の責務で、材料idごとの意味は
  材料カタログ（`domain/material_catalog.py: MATERIAL_CATALOG`の`description`）が持つ。
- 0次ハードフィルタは軸単位ではなく独立した仕組み（`domain/hard_filters.py`）のため、
  本定義には持たない。
- `axis_definitions`DBテーブルが全軸の唯一の正本。起動時（`app/services/
  axis_registry_service.py: refresh_axis_definitions`）にDBから読み込みこのモジュール
  レベルdictへpushするまでは空のまま。本モジュールが持つのは型定義（`AxisDefinition`等）
  と評価用の純粋関数（`evaluate_axis_array`等）のみで、実データは持たない。**行データ
  （軸の新規追加・既存軸の値変更）は`api/routers/axis_admin.py`経由（create/update/
  unpublish→再publish）で行う**。

欠損値の表現はPythonの値で持つ入口がNone、配列がNaN。丸めは区分線形補間系のみ小数1桁で、
Pythonの`round()`と同じ値へ丸める（`difficulty.py: round_difficulty_array`。2進の実際の値で丸める）。
"""

import math
import threading
from collections.abc import Collection, Iterable
from typing import Annotated, Literal, Mapping, Sequence, SupportsFloat, cast

import numpy as np
from cachetools import LRUCache, cached
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    StrictStr,
    Tag,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.domain.attributes import CategoricalColumn, MaterialColumn
from app.domain.axis_templates import evaluate_breakpoint_linear, evaluate_categorical
from app.domain.difficulty import round_difficulty_array, weight_share
from app.domain import material_catalog
from app.domain.material_catalog import WIND_DRAG_RATIO
from app.domain.strict_model import StrictModel
from app.domain.weather_elements import WEATHER_ELEMENTS


#: 軸の宣言に使うモデル共通の設定。`allow_inf_nan=False`は、NaN・無限大の重み・係数が
#: 混じると軸の得点も合成difficultyも黙ってNaNになり、欠損（データが無い）と区別できなく
#: なるため。凍結するのは、評価の途中で辞書へ混ぜ込まれる定義が書き換わらないようにするため。
_AXIS_MODEL_CONFIG = ConfigDict(frozen=True, allow_inf_nan=False)


class MaterialTerm(StrictModel):
    """区分線形補間系shapeの入力1件（材料id・線形結合の係数・欠損時の扱い）。

    `required=True`の材料が欠損（スカラーNone/配列NaN）なら軸全体を欠損として扱う。
    `required=False`の材料の欠損は寄与0として残りだけで評価する（停止密度の軸の
    「信号等のデータが主、交差点データは補助」という非対称な扱いが実例）。ただし全termの材料が
    欠損した場合は、残りが1件も無く「寄与0の合計＝0」と「観測値が0」を区別できないため、
    required有無によらず軸全体を欠損として扱う。
    """

    model_config = _AXIS_MODEL_CONFIG

    material: str = Field(min_length=1)
    weight: float = 1.0
    required: bool = True


class BreakpointLinearShape(StrictModel):
    """区分線形補間（材料の線形結合→前処理→breakpoints折れ線、両端クランプ、小数1桁丸め）。

    合成（他軸参照）は独立したプリミティブではなく、`terms`の各materialが元々材料id・
    軸idのどちらも区別なく指せる設計から生じる性質にすぎない。真偽値フラグの加点合計は
    全termがboolean材料の場合として本shapeで表現する。
    """

    model_config = _AXIS_MODEL_CONFIG

    kind: Literal["breakpoint_linear"] = "breakpoint_linear"
    # 空を許すと下流の壊れ方が三者三様になる（スカラー版はNone、配列版はassert、
    # 地図表示の導出は`terms[0]`/`breakpoints[-1]`でIndexError）。登録時点で弾く。
    terms: list[MaterialTerm] = Field(min_length=1)
    preprocess: Literal["identity", "abs"] = "identity"
    breakpoints: list[tuple[float, float]] = Field(min_length=1)

    @field_validator("breakpoints")
    @classmethod
    def _x_must_be_strictly_ascending(
        cls, value: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """折れ線を引くのは`np.interp`（`axis_templates.py`）で、x昇順を前提に区間を探す。
        崩れた折れ線は例外を出さず、全区間へ無警告で誤った得点を返し続ける。
        """
        xs = [x for x, _ in value]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise axis_error(f"折れ点は横軸の値が小さい順に並べてください（同じ値は使えません）: {xs}")
        return value

    def score_at(self, x: float) -> float:
        """横軸の値`x`の点数（評価と同じ折れ線と丸め）。"""
        return self.scores_at([x])[0]

    def scores_at(self, xs: Sequence[float]) -> list[float]:
        """横軸の値それぞれの点数（`score_at`を1回の配列計算で）。"""
        return _breakpoint_score_array(self, np.asarray(xs, dtype=float), np.zeros(len(xs), dtype=bool)).tolist()

    def smallest_magnitude_at(self, score: float) -> float:
        """丸める前の折れ線で点数が`score`になる横軸の値のうち、0以上で最も小さいもの。符号を畳む軸
        （`preprocess="abs"`）の点数を、その点数に当たる値の大きさへ戻すのに使う。

        0以上の範囲の折れ線が`score`に届かなければ（丸めた点数の平均が端をわずかに越えたとき等）、点数が最も近い節。
        """
        xs = [0.0, *(x for x, _ in self.breakpoints if x > 0)]
        ys = evaluate_breakpoint_linear(np.asarray(xs, dtype=float), self.breakpoints).tolist()
        for x0, y0, x1, y1 in zip(xs, ys, xs[1:], ys[1:]):
            if min(y0, y1) <= score <= max(y0, y1):
                return x0 if y0 == y1 else x0 + (score - y0) * (x1 - x0) / (y1 - y0)
        return min(zip(xs, ys), key=lambda point: abs(point[1] - score))[0]


_FLAG_KEYS = {"true": True, "false": False}


def flag_or_value_name(key: object) -> object:
    """材料の値を書いた文字列の読み方。対応表のキーと0次条件の`equals`が同じ読み方をする。"""
    return _FLAG_KEYS.get(key, key) if isinstance(key, str) else key


class CategoricalShape(StrictModel):
    """カテゴリ値→定数のマッピング（丸めなし。mappingの値がそのままスコアになる）。

    `mapping`のキーはbool（真偽2値の材料）とstr（MATERIAL_CATALOGのdtype="categorical"材料、
    3値以上）の両方を許容する（混在は想定しないが型上は許容）。

    JSONのキーは常に文字列なので、真偽の材料の対応表は"true"/"false"で届く（管理APIの本文・
    `infrastructure/axis_definition_repository.py`のDB往復）。**真偽へ読むのはこの2つの綴りだけ**
    で、それ以外は書いたとおりの値の名前として残す——pydanticの真偽の読み方に任せると
    "yes"・"on"・"1"等の値の名前まで真偽へ化ける。
    """

    model_config = _AXIS_MODEL_CONFIG

    kind: Literal["categorical"] = "categorical"
    material: str = Field(min_length=1)
    # 空の対応表はどの値も引けず、その軸を全区間で恒久的に欠損にする（`evaluate_categorical`
    # は未登録の値へNaNを返すだけで、エラーもログも出さない）。登録時点で弾く。
    mapping: dict[Annotated[StrictBool | StrictStr, BeforeValidator(flag_or_value_name)], float] = Field(
        min_length=1
    )

    @field_validator("mapping", mode="before")
    @classmethod
    def _mapping_must_not_be_empty(cls, value: object) -> object:
        if value == {}:
            raise axis_error("値ごとのスコアを少なくとも1件設定してください。")
        return value


def _shape_kind(value: object) -> str:
    """計算の形の種類。`kind`で見分け、該当する形の誤りだけを返す（見分けないと、ほかの形でも試した結果の
    誤りまで並び、保存の誤りが読めなくなる）。`kind`を持たない値は中身で決める——値の行（`mapping`）を持てば
    種類の形。"""
    if isinstance(value, dict):
        kind = value.get("kind")
        if isinstance(kind, str):
            return kind
        return "categorical" if "mapping" in value else "breakpoint_linear"
    return str(getattr(value, "kind", "breakpoint_linear"))


AxisShape = Annotated[
    Annotated[BreakpointLinearShape, Tag("breakpoint_linear")] | Annotated[CategoricalShape, Tag("categorical")],
    Discriminator(_shape_kind),
]


AxisCategory = Literal["観測", "推定", "動的"]


class PriorityCondition(StrictModel):
    """0次条件: 探索除外のハードフィルタ（`domain/hard_filters.py`、道路そのものを
    探索グラフから除外する）とは別の、**評価を優先確定する**条件。`material`の値が
    `equals`と一致する場合、軸の通常計算（shape評価）を丸ごとスキップし、`value`を
    そのままdifficultyとして返す。

    例: `motor_vehicle_no`（自動車通行不可）が立っている区間を、highway種別等の
    通常の判定に関わらず最良の値で確定する。
    自転車通行禁止（`bicycle=no`）はこれとは異なり、既存の0次ハードフィルタ
    （`no_bicycle`）で道路そのものが探索から除外されるため、この機構は使わない
    （「探索除外」と「評価の優先確定」は別の概念）。

    軸固有のPythonコードへベタ書きせず`AxisDefinition`が共通で持つ宣言にしてあるため、
    同型のケースはコード変更なしに表現できる。
    """

    model_config = _AXIS_MODEL_CONFIG

    material: str = Field(min_length=1)
    equals: str
    value: float


def referenced_materials(shape: "AxisShape", priority_overrides: "Sequence[PriorityCondition]") -> list[str]:
    """`shape`と`priority_overrides`が参照する材料id・軸idの一覧（重複を除き順序は安定）。

    `AxisDefinition.materials`がこれを返し、値の検査`check_axis_definition`と評価の材料の選び（地図の配信が読む
    葉の材料等）の**両方がそれを読む**。片方が`shape.terms`だけを見て他方が`priority_overrides`も見る、という状態に
    なると、検証を素通りした軸が実行時に落ちる（`priority_overrides`経由の静的材料が動的軸へ紛れ込み、
    `evaluate_axis_array`が`materials[override.material]`でKeyErrorになる）。
    """
    if isinstance(shape, BreakpointLinearShape):
        shape_materials = [term.material for term in shape.terms]
    else:
        shape_materials = [shape.material]
    override_materials = [cond.material for cond in priority_overrides]
    # 順序を安定させつつ重複を除く（同じ材料をpriority_overridesとshapeの両方が
    # 参照するケース、例: motor_vehicle_noを他のtermでも使う場合を許容するため）。
    return list(dict.fromkeys([*shape_materials, *override_materials]))


def axis_error(message: str) -> PydanticCustomError:
    """軸の検証の誤り。文は管理画面の保存の誤りにそのまま出るので、利用者が読める日本語で書く
    （`ValueError`は「Value error, 」の前置きが付いて返る）。"""
    return PydanticCustomError("axis_definition", message)


#: 材料の型の呼び名。軸スタジオの材料の選択肢の分け方と同じ語にする。
_DTYPE_NAMES: dict[material_catalog.MaterialDType, str] = {
    "numeric": "数値",
    "boolean": "はい・いいえ",
    "categorical": "種類",
}


def named_references(refs: Iterable[str], axes: Mapping[str, "AxisDefinition"]) -> str:
    """材料・軸の参照を、利用者が画面で見る名前（材料は`MaterialSpec.label`、軸は`label`）で「」に包んで並べる。

    検証・断りの文に使う——idは画面のどこにも出ないので、idで名指すと利用者はどれのことか辿れない。
    材料にも軸にも無い参照は名前を持たないため、idのまま包む。
    """

    def name(ref: str) -> str:
        spec = material_catalog.MATERIAL_CATALOG.get(ref)
        if spec is not None:
            return spec.label
        axis = axes.get(ref)
        return axis.label if axis is not None else ref

    return "".join(f"「{name(ref)}」" for ref in refs)


class AxisDefinition(StrictModel):
    """1つの評価軸の宣言（ADRの`AxisDefinition`スキーマ）。

    `default_weight`はAPIリクエストで上書きされなかった場合の既定の合成重み
    （`RoutePreference`の既定値の単一ソース）。

    `label`/`description`/`category`は一般向けのルート設定画面が
    `GET /api/axis-catalog`経由で表示する（`registry.py`側の表示レジストリ
    [地図レイヤー専用]とは別物——あちらはPython宣言のみでDB化されておらず、GUIで作った
    軸を表現できないため、ルーティング計算を駆動するこちら側に単一ソースを置く）。
    `category`は観測（タグ・POI等の一次属性を直接読む、または単純なフラグ加算のみの軸）／
    推定（複数材料をレシピ・判定式で合成する軸）／動的（時々刻々変わる外部データ由来の軸）
    を区別する。

    **軸の階層**: `shape`の`MaterialTerm.material`/`CategoricalShape.
    material`等は、`MATERIAL_CATALOG`の材料idだけでなく**他の軸のaxis_id**も指せる
    （評価時、既に計算済みの軸のdifficulty値が`materials`辞書へ材料と同じ扱いで
    混ぜ込まれる。`evaluate_axes_array`が依存順に評価して結果を`materials`へ書き足す）。これにより
    「highway基準値」「自転車インフラ」等の細かい推定軸（`is_published=False`、
    一般ユーザーには非公開）を、さらに1段合成した「翻訳結果」として公開軸
    （`is_published=True`）を作る、という階層構造を表現できる。`materials`プロパティは
    材料id・軸id両方を区別なく返すため、材料の排他帰属チェック
    （`check_material_exclusivity`）は`MATERIAL_CATALOG`に実在するものだけを対象に
    絞り、軸参照は対象外とする（複数の公開軸が同じ内部軸を参照するのは意図的な共有で
    あり、材料の二重計上とは別の話のため）。
    """

    model_config = _AXIS_MODEL_CONFIG

    axis_id: str = Field(min_length=1)
    shape: AxisShape
    # 負の重みは合成difficultyの分母（重みの総和）と分子の符号を食い違わせ、良い経路ほど
    # 高い点数になる。上限は設けない（極端な値は利用者の選択として通す）。
    default_weight: float = Field(ge=0)
    #: 空を許すと、ルート設定画面にもルート結果にも名前の出ない軸を登録できてしまう。
    label: str = Field(min_length=1)
    description: str = ""
    # 軸スタジオが作る軸は常に「推定」（複数材料を判定式で合成する軸）。「観測」（タグ・POIを
    # そのまま読む）「動的」（気象等、時々刻々変わる外部データ由来）はどちらも材料そのものの性質で、
    # 材料を組み合わせて判定式を作る仕組みからは生み出せない。
    category: AxisCategory = "推定"
    # 公開済み軸は一般向け`GET /api/axis-catalog`（一般ユーザーの保存設定が
    # axis_idキーで再現されるため、公開後の破壊的変更・削除は他ユーザーの設定を黙って
    # 壊す）に出る一方、下書き軸は管理API（軸スタジオ）でのみ見える。既定Falseは
    # 「新規作成した軸はまず下書き」という安全側の初期値。このフラグは
    # 「内部軸（他の軸から参照される専用、恒久的に非公開のまま運用）」の表現にも流用する
    # （新フィールドを増やさず既存の仕組みを再利用する）。
    is_published: bool = False
    # 0次条件（軸の通常計算より前に評価される優先確定ルール）。空リストは
    # 「無し」（shapeだけで評価）で、対象外の軸の挙動には影響しない。
    priority_overrides: list[PriorityCondition] = Field(default_factory=list)
    icon_id: str | None = None
    """ルート設定・ルート結果の評価の内訳で軸の名前に添えるアイコンのid。画面が持つ固定のパレットから選び、
    画面の知らないid・未設定は汎用のアイコンで出る。パレットへ形を足すには画面のコード変更が要る。"""
    time_scope: Literal["always", "night_only"] = "always"
    """この軸の重みが常に有効か、特定の時間帯でのみ有効かの宣言。
    「`time_scope != "always"`な軸の重みを、その時間帯に区間を通るときだけ残し、ほかは0倍にする」
    という汎用ロジック（`domain/axis_definitions.py: time_scoped_weights`参照）が、このフィールドだけを
    見て判定する。別の時間帯を足すときもこのLiteralへ値を1つ増やすだけで、エンジン側の
    コード変更は要らない。"""
    display_thresholds_override: list[float] | None = Field(default=None, min_length=1)
    """地図の色分けしきい値だけを差し替える軽量な上書き。未設定なら`breakpoints`のX軸の
    値がそのまま段の境界になる。

    材料をどう合成して1つの表示用の値にするかは厳密に導けるが、段の刻み方は
    `breakpoints`のX軸を流用するため粗くなりがちで、見やすさのために細かく刻みたいという
    正当なニーズがある。導出能力ではなく好みの問題なので、しきい値だけを独立させてある。

    値は`breakpoints`のX軸と同じ材料スケール（実行時スケール変換が要る材料を含む軸でも
    変換後のスケールなので、係数が変わっても書き直さなくてよい）。地図表示そのものを
    導けない軸には効果が無い。"""
    display_band_labels_override: list[str] | None = None
    """地図の色分け段階に添える体感ラベル。未設定は
    段階の数値レンジ表記（例:「2〜6」）のみを凡例に出す。

    `display_thresholds_override`と対になる概念（どちらも「地図の色分け段階の見せ方」の
    軸ごとの好み）で、dedicated_way_value_layer軸だけでなく、通常のramp軸の凡例にも
    同じ仕組みで使える。"""
    dedicated_way_value_layer: bool = False
    """**ルート未確定時**の地図が、この軸を配信（`/api/region/dynamic-way-values`、`services/dedicated_way_values.py`）の
    値で塗るかの宣言。配信はどの公開軸の値も返すので、この印は塗り方を選ぶだけで、配信できるかを表さない。
    `axis_id`の文字列比較によるハードコード分岐ではなく、性質ベースの宣言的フィールドとして持たせ、軸スタジオの
    編集画面（管理API）からも設定できるようにする。

    **ルート確定後**の地図色分け（ルート結果の`axis_difficulties[axis_id]`でルート線を段に塗る。公開軸なら自動的に
    対象になりこのフィールドとは無関係）とは別の概念であることに注意。"""

    @field_validator("display_thresholds_override")
    @classmethod
    def _thresholds_must_be_strictly_ascending(cls, value: list[float] | None) -> list[float] | None:
        return None if value is None else cls.check_display_thresholds_ascending(value)

    @field_validator("label", mode="before")
    @classmethod
    def _label_must_not_be_empty(cls, value: object) -> object:
        if value == "":
            raise axis_error("表示名を入力してください。")
        return value

    @field_validator("display_thresholds_override", mode="before")
    @classmethod
    def _thresholds_override_must_not_be_empty(cls, value: object) -> object:
        if value == []:
            raise axis_error("色分けのしきい値を1件以上入力するか、上書きをオフにしてください。")
        return value

    @staticmethod
    def check_display_thresholds_ascending(value: list[float]) -> list[float]:
        """受け取る側は段の境界を昇順の前提で読む（地図はMapLibreの`step` expressionで塗り、
        そのstopは昇順でなければならない）。降順・同値が混じると、地図とルート線が別の段で塗られる。
        """
        if any(b <= a for a, b in zip(value, value[1:])):
            raise axis_error(f"色分けのしきい値は小さい順に並べてください（同じ値は使えません）: {value}")
        return value

    @model_validator(mode="after")
    def _band_labels_must_match_the_bands(self) -> "AxisDefinition":
        """段ラベルは段と1対1で対応する。しきい値を自動導出へ任せたまま段数だけ決め打つと、
        導出結果が変わった日に凡例のラベルが実際の段とずれる。
        """
        if self.display_band_labels_override is None:
            return self
        if self.display_thresholds_override is None:
            raise axis_error("段のラベルを上書きするときは、色分けのしきい値も上書きしてください（段の数が決まらないため）。")
        expected = len(self.display_thresholds_override) + 1
        if len(self.display_band_labels_override) != expected:
            raise axis_error(
                f"段のラベルは{expected}件にしてください（しきい値{len(self.display_thresholds_override)}件で"
                f"段は{expected}つ。いまは{len(self.display_band_labels_override)}件）。"
            )
        return self

    @property
    def materials(self) -> list[str]:
        """この軸が参照する材料id・軸idの一覧（shapeから導出。二重管理しない。
        `priority_overrides`が参照する材料も含む）。呼び出し側が材料か軸かを
        区別する必要がある場合は`material_catalog.is_known_material`で判別する
        （`check_material_exclusivity`参照）。"""
        return referenced_materials(self.shape, self.priority_overrides)


# `axis_definitions`DBテーブルが唯一の正本で、起動時（app/services/
# axis_registry_service.py: refresh_axis_definitions）にDBから読み込みこの辞書を
# in-placeで書き換えるまでは空のまま。新規軸の追加・既存軸の変更は`api/routers/
# axis_admin.py`経由で行う
# （モジュールdocstring参照）。
AXIS_DEFINITIONS: dict[str, AxisDefinition] = {}

# 差し替え（`replace_axis_definitions`）と写し（`copy_axis_definitions`）を互いに排他にする。
# 差し替えはイベントループで動くので、ループの上で読む側は途中を見ない。見うるのは
# `asyncio.to_thread`の先で読む側だけで、そちらは写しを取って読む。
_AXIS_DEFINITIONS_LOCK = threading.Lock()


def replace_axis_definitions(definitions: Mapping[str, AxisDefinition]) -> None:
    """`AXIS_DEFINITIONS`の中身を`definitions`へ差し替える（同じdictのまま。モジュールdocstring参照）。"""
    with _AXIS_DEFINITIONS_LOCK:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(definitions)


def copy_axis_definitions() -> dict[str, AxisDefinition]:
    """`AXIS_DEFINITIONS`の写し。別スレッドで軸を読む処理は、入口でこれを1回取り、終わりまでこれだけを読む。

    `AXIS_DEFINITIONS`を直に読むと、読む間に軸の保存が差し替えて、鍵が欠ける（`KeyError`）・
    回している辞書の大きさが変わる（`RuntimeError`）・読むたびに軸の集合が食い違う。
    """
    with _AXIS_DEFINITIONS_LOCK:
        return dict(AXIS_DEFINITIONS)


class AxisMaterialConflictError(ValueError):
    """新規/更新しようとした軸の材料が、既存の別軸と重複している場合に送出する。

    「1つの材料は原則1つの軸だけが使う」原則を、ルーティング計算を駆動する軸の集合の検査
    （`check_axis_set`。起動時の読み込みと書き込みの両方が通す）で強制する。軸スタジオで
    任意の軸を登録できるため、既存軸が使う材料を新軸が黙って再利用し二重計上が混入する
    事故を構造的に防ぐ。
    """

    def __init__(self, candidate: "AxisDefinition", conflicting: "AxisDefinition", overlapping_materials: set[str]) -> None:
        self.axis_id = candidate.axis_id
        self.conflicting_axis_id = conflicting.axis_id
        self.overlapping_materials = overlapping_materials
        other = named_references([conflicting.axis_id], {conflicting.axis_id: conflicting})
        super().__init__(
            f"材料{named_references(sorted(overlapping_materials), {})}は、すでに軸{other}が使っています"
            f"（1つの材料は1つの軸でだけ数えます）。別の材料を選ぶか、{other}を「ほかの軸」として組み合わせてください。"
        )


#: 公開済みの軸に拒む操作。
PublishedAxisAction = Literal["updated", "deleted"]


class AxisPublishedImmutableError(ValueError):
    """公開済み（is_published=True）の軸を更新・削除しようとした場合に送出する。

    一般ユーザーの保存設定（RouteSettingsPanelのプリセット・重み）はaxis_idキーで
    再現されるため、公開後の破壊的変更・削除は他ユーザーの設定を黙って壊す。
    改良したい場合は複製（新しいaxis_idの下書き軸として作成）してから公開する導線を
    UI側に用意する（この関数は変更を一切拒否するのみで、複製自体は関与しない）。

    ただし更新（`action="updated"`）については、`_COSMETIC_ONLY_FIELDS`のみの差分
    （評価ロジック・重みに一切影響しない見た目専用の変更）なら例外的に許可する
    （`check_publish_immutability`の`candidate`引数参照）。評価結果に影響しうる
    変更・削除は不変という原則自体は変えない。
    """

    def __init__(self, existing: "AxisDefinition", action: PublishedAxisAction) -> None:
        self.axis_id = existing.axis_id
        self.action = action
        name = named_references([existing.axis_id], {existing.axis_id: existing})
        if action == "deleted":
            message = f"{name}は公開中のため削除できません。先に非公開に戻してください。"
        else:
            message = (
                f"{name}は公開中のため、表示以外は変えられません。非公開に戻してから変えるか、"
                "複製して新しい軸として作ってください。"
            )
        super().__init__(message)


# 評価ロジック（shape・default_weight・priority_overrides等）に一切影響しない
# 表示専用フィールドのみ、公開済み軸でも直接更新を許可する（unpublish→update→republishの
# 手順を経由しなくてよい）。値を変えてもaxis_idキーで再現される他ユーザーの保存重み設定・
# ルート計算結果は変わらないため、公開後の破壊的変更を防ぐという目的を損なわない。
# display_band_labels_overrideもdisplay_thresholds_overrideと同じ「地図の色分け段階の
# 見せ方」の表示専用フィールドのためここへ加える。
_COSMETIC_ONLY_FIELDS = frozenset(
    {
        "icon_id",
        "display_thresholds_override",
        "display_band_labels_override",
    }
)


def is_cosmetic_only_update(existing: AxisDefinition, candidate: AxisDefinition) -> bool:
    """`existing`から`candidate`への差分が`_COSMETIC_ONLY_FIELDS`だけかどうかを判定する。
    `existing`へ`candidate`側の表示専用フィールドだけを重ねた結果が
    `candidate`と完全一致すれば、それ以外のフィールドは変わっていないと分かる。"""
    patched = existing.model_copy(update={field: getattr(candidate, field) for field in _COSMETIC_ONLY_FIELDS})
    return patched == candidate


def check_publish_immutability(
    existing: AxisDefinition, action: PublishedAxisAction, candidate: AxisDefinition | None = None
) -> None:
    """`existing`が公開済みなら`AxisPublishedImmutableError`を送出する（更新・削除の
    どちらの直前でも呼べる汎用関数、`action`は断りの文を選ぶ）。

    `candidate`（更新後の内容）が渡され、かつその差分が表示専用
    フィールドのみ（`is_cosmetic_only_update`）の場合は例外的に許可する。`delete()`のように
    `candidate`が無い呼び出しは一律拒否のまま。"""
    if existing.is_published and not (candidate is not None and is_cosmetic_only_update(existing, candidate)):
        raise AxisPublishedImmutableError(existing, action)


def check_material_exclusivity(candidate: AxisDefinition, existing: dict[str, AxisDefinition]) -> None:
    """`candidate`の材料が`existing`内の他軸と重複していないか検査する。

    `existing`に`candidate.axis_id`と同じキーが含まれていても（更新時、自分自身との
    比較になるため）スキップする。重複が見つかれば`AxisMaterialConflictError`を送出する
    （登録は行わない、呼び出し元の責務）。

    複数軸が参照してよい共通コンテキスト（距離等）の材料は無いため、`shared`相当の
    フラグは持たない。

    `candidate.materials`は材料idと軸id（軸の階層構造、他の軸への参照）を
    区別せずに返すため、`MATERIAL_CATALOG`に実在するものだけを検査対象とする
    （`is_known_material`でフィルタ）。軸参照は複数の公開軸が同じ内部軸を意図的に
    共有できる設計のため、この排他チェックの対象外——材料の二重計上とは別の話。
    """
    candidate_materials = {m for m in candidate.materials if material_catalog.is_known_material(m)}
    for other_id, other in existing.items():
        if other_id == candidate.axis_id:
            continue
        overlap = candidate_materials & {m for m in other.materials if material_catalog.is_known_material(m)}
        if overlap:
            raise AxisMaterialConflictError(candidate, other, overlap)


class AxisDependencyCycleError(ValueError):
    """軸間の依存関係（他の軸をmaterialとして参照する構造）に循環があった場合に
    送出する。"""

    def __init__(self, cycle: list[str], definitions: Mapping[str, "AxisDefinition"]) -> None:
        self.cycle = cycle
        chain = "→".join(named_references([axis_id], definitions) for axis_id in cycle)
        super().__init__(f"軸の組み合わせが輪になっています（{chain}）。どこか1か所の組み合わせを外してください。")


def axis_dependencies(definition: AxisDefinition, known_axis_ids: set[str]) -> set[str]:
    """`definition`が参照する軸id（materialsのうち、材料ではなく軸を指すもの）を返す。
    `known_axis_ids`は循環検出・評価順序決定の対象となる軸id全体
    （通常は`AXIS_DEFINITIONS`のキー集合）。"""
    return {m for m in definition.materials if not material_catalog.is_known_material(m) and m in known_axis_ids}


def _leaf_materials(definition: AxisDefinition) -> list[str]:
    """内部軸を辿り切った先の材料idを、定義順・重複なしで返す。

    `AxisDefinition.materials`は1段しか展開せず、材料idと軸idが混ざって返る。軸を参照する
    軸は葉まで降りないと材料が分からないため、辿る側がそれぞれ再帰を書かずに済むよう
    ここに1本だけ置く。循環は軸スタジオが拒否するが、`visited`で止めて安全側に倒す。
    """
    leaves: list[str] = []
    visited: set[str] = set()

    def descend(current: AxisDefinition) -> None:
        if current.axis_id in visited:
            return
        visited.add(current.axis_id)
        for ref in current.materials:
            referenced_axis = AXIS_DEFINITIONS.get(ref)
            if referenced_axis is not None:
                descend(referenced_axis)
            else:
                leaves.append(ref)

    descend(definition)
    return list(dict.fromkeys(leaves))


def primary_attribute_ids_for(definition: AxisDefinition) -> list[str]:
    """軸が最終的に見ている一次属性id。一次属性を持たない材料は現れない。"""
    return list(
        dict.fromkeys(
            spec.primary_attribute.attr_id
            for material_id in _leaf_materials(definition)
            if (spec := material_catalog.MATERIAL_CATALOG.get(material_id)) is not None
            and spec.primary_attribute is not None
        )
    )


def weather_layer_groups_for(definition: AxisDefinition) -> list[str]:
    """軸の材料の元データを描く気象のチップ（`WEATHER_LAYER_GROUPS`の名前）。一次属性を持つ材料は現れない。"""
    grid_values = {
        spec.weather_grid_value
        for material_id in _leaf_materials(definition)
        if (spec := material_catalog.MATERIAL_CATALOG.get(material_id)) is not None and spec.weather_grid_value is not None
    }
    return list(dict.fromkeys(element.group for element in WEATHER_ELEMENTS if element.grid_value in grid_values))


class AxisInternalAxisPublishError(ValueError):
    """他の軸から参照されている内部軸を公開（is_published=True）しようとした場合に
    送出する。

    「内部軸は他の軸から参照される専用で、恒久的に非公開のまま運用する」という軸階層の
    設計意図（本モジュールのAxisDefinition docstring「軸の階層」参照）をコードレベルで
    強制する。内部軸が誤って公開されると、一般ユーザー向けのルート設定画面
    （`GET /api/axis-catalog`、is_publishedフィルタのみ）へそのまま漏れ出てしまう。
    """

    def __init__(self, candidate: "AxisDefinition", referencing: "AxisDefinition") -> None:
        self.axis_id = candidate.axis_id
        self.referencing_axis_id = referencing.axis_id
        axes = {candidate.axis_id: candidate, referencing.axis_id: referencing}
        super().__init__(
            f"{named_references([candidate.axis_id], axes)}は{named_references([referencing.axis_id], axes)}が組み合わせに使っている軸なので、"
            "公開できません（組み合わせに使う軸は非公開のまま使います）。公開せずに保存してください。"
        )


def check_internal_axis_not_published(candidate: AxisDefinition, existing: dict[str, AxisDefinition]) -> None:
    """`candidate`が`existing`内の他の軸（自分自身を除く）から軸参照（内部軸）として
    使われているにもかかわらず、is_published=Trueで保存しようとしていないか検査する。
    非公開のままなら常に許可する（早期return）。

    断るのは公開へ切り替える書き込みだけで、`existing`にある書く前の版が既に公開中なら許可する。
    時刻で変わる軸が公開軸を組み合わせる形（`check_axis_set`のdocstring参照）では、組み合わせに
    使われる軸が公開中のまま残り、その表示だけの直し（`check_publish_immutability`が許す差分）も保存する。
    """
    previous = existing.get(candidate.axis_id)
    if not candidate.is_published or (previous is not None and previous.is_published):
        return
    known_axis_ids = set(existing) | {candidate.axis_id}
    for other_id, other in existing.items():
        if other_id == candidate.axis_id:
            continue
        if candidate.axis_id in axis_dependencies(other, known_axis_ids):
            raise AxisInternalAxisPublishError(candidate, other)


def check_axis_definition(definition: AxisDefinition, axes: Mapping[str, AxisDefinition]) -> None:
    """軸の値の不変条件のうち、軸の外（材料カタログ・ほかの軸）に照らすもの。

    書き手を問わず成り立つべきもので、管理APIの本文（`AxisDefinitionPayload`）も、起動時の読み込み
    （`services/axis_registry_service.py: refresh_axis_definitions`。バックアップから戻した行もここで初めて通る）も通す。`AxisDefinition`の
    検証に置かないのは、保存済みの行を読み出す管理APIの一覧・単体取得が、通らなくなった行（材料を
    カタログから外した後の軸等）もそのまま見せて直させる必要があるため。

    `axes`は、材料idでない参照を軸の参照として受け入れる軸（誤りの文ではその表示名で名指す）。誤りは`axis_error`。
    """
    _check_dynamic_and_static_materials_are_not_mixed(definition)
    _check_references(definition, axes)
    _check_density_axis_is_a_line(definition)


def averages_density(definition: AxisDefinition) -> bool:
    """1kmあたりの量（密度）の重み付き和を折れ線に通す軸（密度の軸）か。

    密度の軸は、区間をまたいだ値（ビン・候補）を横軸の値の距離平均（回数÷距離）から点数にし、探索の費用では
    区間の回数に比例する足し算として持つ（`evaluation.py: compose_costs_from_axis_matrix`）。どちらも回数だけで
    決まり、道の切り方に依らない。そのため折れ線は(0, 0)から始まる直線に限る（`_check_density_axis_is_a_line`）。

    - 足せる材料（`MaterialSpec.additive`。どれも1kmあたりの密度）だけを項に持つ。他の軸を項に持つ軸は、
      中の軸の点数が密度でないため外す。勾配（%）のような密度でない材料も、短い急坂を平均でならすと
      坂のつらさが消えるため外す。
    - 前処理が無い（`abs`は平均と絶対値の順を入れ替えると値が変わる）。
    """
    shape = definition.shape
    if not isinstance(shape, BreakpointLinearShape) or shape.preprocess != "identity":
        return False
    terms = [term for term in shape.terms if term.weight != 0]
    return bool(terms) and all(
        (spec := material_catalog.MATERIAL_CATALOG.get(term.material)) is not None and spec.additive for term in terms
    )


def density_slope(shape: BreakpointLinearShape) -> float:
    """密度の軸の折れ線の傾き（横軸の値1あたりの点数）。折れ線は(0, 0)と、点数が頭打ちになるもう1点の2つ。"""
    x, y = shape.breakpoints[-1]
    return y / x


def _check_density_axis_is_a_line(definition: AxisDefinition) -> None:
    """密度の軸（`averages_density`）の折れ線は、(0, 0)ともう1点の2つの折れ点に限る。

    折れ線が上に凸だと、信号のように短い区間に回数が集まる道では、区間ごとの点数の和が回数どおりより低く出て、差が
    道の切り方で決まる。探索の費用は回数×傾きで足すので、傾きが1つに決まらない折れ線では探索とルートの値が食い違う。
    """
    if not averages_density(definition):
        return
    breakpoints = cast(BreakpointLinearShape, definition.shape).breakpoints
    if len(breakpoints) != 2 or tuple(breakpoints[0]) != (0.0, 0.0):
        raise axis_error(
            "1kmあたりの回数・件数の材料だけを組み合わせる軸は、折れ点を「0のとき0点」ともう1点の2つにしてください"
            f"（点数を回数に比例させ、もう1点より先はその点数で止めるため）。いまの折れ点: {[tuple(p) for p in breakpoints]}"
        )


def _check_dynamic_and_static_materials_are_not_mixed(definition: AxisDefinition) -> None:
    """動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）と静的材料を同じ軸で混在させない。

    動的軸はリクエストごとに`evaluate_dynamic_axis_arrays`（domain/dynamic_materials.py）で
    再評価され、そこへ渡るのは「静的スコア行列の公開軸スコア」と「動的材料」だけである。
    静的材料の配列は渡らないため、混在させた軸は`evaluate_axis_array`が`materials[...]`で
    KeyErrorになり、`/api/routes/generate`ごと失敗する。静的材料が必要なら、その部分を別の軸へ
    切り出し（公開軸として評価され、動的軸からは軸参照で読める）合成する。

    参照材料は`definition.materials`（`priority_overrides`が参照する材料も含む）——動的軸かどうかを
    判定する`_axes_depending_on_materials`が同じ導出を根拠にしているため、ここだけ`shape.terms`に
    絞ると検証を素通りした軸が実行時に落ちる。
    """
    materials = set(definition.materials)
    dynamic = materials & REQUEST_DYNAMIC_MATERIAL_IDS
    # 軸参照（他の軸のaxis_id）は静的材料ではないため除く。
    static = {m for m in materials if material_catalog.is_known_material(m)} - REQUEST_DYNAMIC_MATERIAL_IDS
    if dynamic and static:
        raise axis_error(
            f"時刻で変わる材料{named_references(sorted(dynamic), {})}と、変わらない材料{named_references(sorted(static), {})}は"
            "1つの軸で組み合わせられません（時刻で変わる評価には、時刻で変わる材料と公開軸の点数しか届かないため）。"
            "変わらない材料で別の軸を作り、「ほかの軸」として組み合わせてください。"
        )


def _check_references(definition: AxisDefinition, axes: Mapping[str, AxisDefinition]) -> None:
    """shapeと0次条件が指す材料・軸が既知で、材料の型がその使われ方に合うこと。

    どれも破っても評価はエラーもログも出さず、その軸（または条件）が全区間で恒久的に効かなくなる:

    - `CategoricalShape`はboolean/categorical材料を前提とする。numeric材料（例: maxspeed_kmh）を
      指すと、`axis_templates.evaluate_categorical`は対応表のキーと一致する値しか引けないため常にNaNになる。
      `BreakpointLinearShape`はnumeric/boolean材料を前提とする——項の計算は`value * term.weight`の
      乗算なので真偽の値も`True==1.0`/`False==0.0`として正しく計算され、numeric/booleanの混在も許す。
    - 対応表のキーの型（bool/str）は材料の型と一致すること。型の「種類」だけを見ると、分類の材料
      （値は"residential"等の文字列）に真偽のキーの対応表を置けてしまい、常に引けない。
    - 0次条件は、当たる値のある材料（真偽・分類）にだけ置け、`equals`を対応表のキーと同じ読み方
      （`flag_or_value_name`）で読んだ値の型が材料の値の型と合うこと（真偽の材料に"yes"等は当たらない）。

    軸参照は型の検査の対象外（評価結果は常に0-100の数値）。循環と参照先の実在の組み合わせは
    `topological_axis_order`が見る。
    """
    shape = definition.shape
    materials = referenced_materials(shape, ())
    expected_dtypes: tuple[material_catalog.MaterialDType, ...] = (
        ("numeric", "boolean") if isinstance(shape, BreakpointLinearShape) else ("boolean", "categorical")
    )
    unknown = sorted({m for m in materials if not material_catalog.is_known_material(m) and m not in axes})
    if unknown:
        raise axis_error(f"存在しない材料・軸を指しています（{', '.join(unknown)}）。点数の決め方で選び直してください。")
    mismatched = sorted({m for m in materials if material_catalog.is_known_material(m) and material_catalog.material_dtype(m) not in expected_dtypes})
    if mismatched:
        kinds = "・".join(_DTYPE_NAMES[dtype] for dtype in expected_dtypes)
        raise axis_error(
            f"材料{named_references(mismatched, axes)}は、この点数の決め方には使えません（使えるのは{kinds}の材料）。"
        )
    if isinstance(shape, CategoricalShape) and material_catalog.is_known_material(shape.material):
        dtype = material_catalog.MATERIAL_CATALOG[shape.material].dtype
        key_types = {type(key) for key in shape.mapping}
        expected_key_type = bool if dtype == "boolean" else str
        if key_types and key_types != {expected_key_type}:
            keys = "「はい」「いいえ」" if dtype == "boolean" else "値の名前"
            raise axis_error(
                f"{named_references([shape.material], axes)}は{_DTYPE_NAMES[dtype]}の材料なので、"
                f"値ごとの点数の行は{keys}で書いてください。"
            )
    unknown_override_materials = sorted(
        {
            cond.material
            for cond in definition.priority_overrides
            if not material_catalog.is_known_material(cond.material) and cond.material not in axes
        }
    )
    if unknown_override_materials:
        raise axis_error(f"優先条件が存在しない材料・軸を指しています（{', '.join(unknown_override_materials)}）。")
    for cond in definition.priority_overrides:
        override_dtype = material_catalog.material_dtype(cond.material)
        if override_dtype not in ("boolean", "categorical"):
            kind = "軸" if override_dtype is None else "数値の材料"
            raise axis_error(
                f"優先条件は、はい・いいえか種類の材料にだけ置けます（{named_references([cond.material], axes)}は{kind}です）。"
            )
        expected_type = bool if override_dtype == "boolean" else str
        if not isinstance(flag_or_value_name(cond.equals), expected_type):
            raise axis_error(
                f"優先条件の値「{cond.equals}」は{named_references([cond.material], axes)}の値として読めません"
                "（はい・いいえの材料は\"true\"か\"false\"、種類の材料は値の名前で書いてください）。"
            )


def _topological_axis_order_cache_key(
    definitions: dict[str, AxisDefinition],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((axis_id, tuple(definition.materials)) for axis_id, definition in definitions.items())


@cached(cache=LRUCache(maxsize=64), key=_topological_axis_order_cache_key)
def topological_axis_order(definitions: dict[str, AxisDefinition]) -> list[str]:
    """軸を「依存先（参照される軸）が先」の順序に並べ替える（深さ優先探索による
    トポロジカルソート）。循環参照があれば`AxisDependencyCycleError`を
    送出する。どの軸からも参照されない軸（公開軸）同士の相対順序は`definitions`の挿入順
    （`sort_order`）を保つ——公開軸だけに絞ったこの並びが静的スコア行列の列の並びで、
    合成（`difficulty.py`のNeumaier加算）の加算順になる。標準ライブラリの
    `graphlib.TopologicalSorter`は準備のできた軸から幅優先で出すため、内部軸を参照する
    公開軸が参照しない公開軸の後ろへ回り、この順序を保たない。

    スカラー評価がEdge単位（1ルート候補あたり
    最大数百回）で呼ぶホットパスのため、結果をプロセス内メモリでメモ化する。キーは
    各軸の`materials`（依存関係を決める唯一の入力）から導出した内容ベースの値であり、
    `AXIS_DEFINITIONS`自体のオブジェクト同一性には依存しない（`replace_axis_definitions`が
    同一オブジェクトのまま中身だけ差し替えるため、オブジェクトidベースのキーだと差し替え後も
    古いキャッシュを誤って返しうる）。循環参照（`AxisDependencyCycleError`）はキャッシュ
    しない（軸スタジオでの試行錯誤中に一時的な循環を経て修正された場合の再評価を妨げない
    ため）。
    """
    known_axis_ids = set(definitions.keys())
    order: list[str] = []
    visited: dict[str, int] = {}  # 0=visiting, 1=done

    def visit(axis_id: str, path: list[str]) -> None:
        state = visited.get(axis_id)
        if state == 1:
            return
        if state == 0:
            raise AxisDependencyCycleError([*path, axis_id], definitions)
        visited[axis_id] = 0
        for dep in sorted(axis_dependencies(definitions[axis_id], known_axis_ids)):
            visit(dep, [*path, axis_id])
        visited[axis_id] = 1
        order.append(axis_id)

    for axis_id in definitions:
        visit(axis_id, [])
    return order


def check_axis_set(definitions: dict[str, AxisDefinition]) -> None:
    """軸の集合を受け入れるか。軸1本ずつの`check_axis_definition`では見えない、集合で決まる不変条件。

    - 軸idが材料idと重ならない: 軸の評価結果は材料と同じ辞書へ書き戻されるため、重なると同名の材料の値を
      黙って上書きし、それ以降に評価される軸が壊れる。
    - 1つの材料を2つの軸で数えない（`check_material_exclusivity`）。重なりは後に並ぶ軸の誤りとして名指す
      ——書き込みは書いた軸を最後に並べて渡すので、断りの文が書いた軸の側から読める。
    - 組み合わせが輪にならない（`topological_axis_order`）。

    起動時の読み込み（バックアップから戻した行も）と管理APIの書き込みの両方がこれを通す。内部軸を公開しないことは
    含めない——時刻で変わる軸が公開軸を組み合わせる形（`_check_dynamic_and_static_materials_are_not_mixed`が案内する）を
    拒むことになるため、書き込みの`check_internal_axis_not_published`だけが見る。
    """
    earlier: dict[str, AxisDefinition] = {}
    for axis_id, definition in definitions.items():
        if material_catalog.is_known_material(axis_id):
            raise ValueError(f"axis_id={axis_id} は既存の材料idと衝突しています")
        check_material_exclusivity(definition, earlier)
        earlier[axis_id] = definition
    topological_axis_order(definitions)


# リクエストごとに値が変わりうる材料id（風向・風速・走行速度由来）。`MATERIAL_CATALOG`の
# `value_sql=None`は「SQLでは求められない」という別の意味も持つ（動的データ以外に、
# 評価へ配線していない材料もNoneになる）ため流用せず、ここに正準定義を置く。
# `dynamic_axis_topological_order`がこの集合を起点に、依存する軸を機械的に導出する
# （軸id・材料idのハードコードを個別の軸ぶん増やさない汎用設計）。各材料の評価関数は
# `domain/dynamic_materials.py: DYNAMIC_MATERIAL_EVALUATORS`に1対1で登録する。
REQUEST_DYNAMIC_MATERIAL_IDS = frozenset({WIND_DRAG_RATIO})


def _axes_depending_on_materials(
    material_ids: frozenset[str], definitions: dict[str, AxisDefinition]
) -> set[str]:
    """`definitions`内の各軸が、`material_ids`のいずれかを直接、または他の軸を介して
    間接的に参照しているかを固定点反復で判定する。"""
    dynamic: set[str] = set()
    changed = True
    while changed:
        changed = False
        for axis_id, definition in definitions.items():
            if axis_id in dynamic:
                continue
            if any(m in material_ids or m in dynamic for m in definition.materials):
                dynamic.add(axis_id)
                changed = True
    return dynamic


@cached(cache=LRUCache(maxsize=64), key=_topological_axis_order_cache_key)
def dynamic_axis_topological_order(definitions: dict[str, AxisDefinition]) -> list[str]:
    """`definitions`内の軸のうち`REQUEST_DYNAMIC_MATERIAL_IDS`へ直接・間接に依存する軸を、
    依存順（`topological_axis_order`のサブセット）で返す。

    `evaluate_dynamic_axis_arrays`（domain/dynamic_materials.py）が、探索範囲の材料から
    求めた静的軸別スコア行列（この関数が返す軸id集合には含まれない
    列はNaN）はそのまま使い、この関数が返す軸だけをリクエスト時に動的材料（風等）を
    組み込んで再評価するために使う。軸スタジオが新しく作る軸が風（または風に依存する
    既存軸）を参照した場合も、ハードコード無しでこの集合へ自動的に含まれる。

    `topological_axis_order`と同じ理由（タイル読込時・リクエスト時の両方で呼ばれる）で
    プロセス内メモリへ内容ベースのキーでメモ化する。
    """
    dynamic_ids = _axes_depending_on_materials(REQUEST_DYNAMIC_MATERIAL_IDS, definitions)
    return [axis_id for axis_id in topological_axis_order(definitions) if axis_id in dynamic_ids]


def published_axis_definitions(definitions: Mapping[str, AxisDefinition] | None = None) -> list[AxisDefinition]:
    """公開軸（`is_published=True`）を宣言の順に。`definitions`を省くと今の`AXIS_DEFINITIONS`。

    内部軸（`is_published=False`）は一般ユーザーの重み付け対象外で、軸カタログにも出ない。"""
    return [definition for definition in (AXIS_DEFINITIONS if definitions is None else definitions).values()
            if definition.is_published]


def default_axis_weights() -> dict[str, float]:
    """axis_idキーの既定重み辞書（APIで上書きされる前の値、`RoutePreference`の
    既定値）。値は各軸の`default_weight`で、`GET /api/axis-catalog`が軸ごとに配る
    `default_weight`と同じ。公開軸だけを持つ（`published_axis_definitions`）。
    `RoutePreference`のバリデーション（未知のaxis_idを拒否）もこの集合と整合させる。"""
    return {definition.axis_id: definition.default_weight for definition in published_axis_definitions()}


def weight_share_when_published(definition: AxisDefinition, definitions: Mapping[str, AxisDefinition]) -> float | None:
    """`definition`を（保存した既定の重みで）公開したとき、公開軸の既定の重みの合計に占める割合。公開済みの軸は今の
    割合。分母は`definitions`の公開軸で、合計が0ならNone（`difficulty.weight_share`）。"""
    others = [other.default_weight for other in published_axis_definitions(definitions)
              if other.axis_id != definition.axis_id]
    return weight_share(definition.default_weight, others)


def time_scoped_weights(
    weights: Mapping[str, float], active_scopes: Mapping[str, np.ndarray]
) -> dict[str, float | np.ndarray]:
    """`weights`のうち、`time_scope`が"always"以外（AXIS_DEFINITIONS参照）の軸の重みを、
    その時間帯に当たる区間（`active_scopes`の真偽の配列。区間の並び）でだけ残し、ほかの区間では
    0.0にした配列へ置き換えた新しい辞書を返す（`weights`自体は変更しない）。`active_scopes`に無い
    時間帯は、どの区間も当たらないとして扱う。

    エンジン側は「この性質を持つ軸を探して掛け替える」という汎用ロジックだけを持つため、
    軸を足すときに要るのはその軸の`time_scope`を設定することだけになる。

    `weights`に無いaxis_id（内部軸・非公開化された軸等）は重みを持たないため、キーを足さずに
    無視する。"""
    scoped: dict[str, float | np.ndarray] = dict(weights)
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if axis_id in weights and definition.time_scope != "always":
            active = active_scopes.get(definition.time_scope)
            scoped[axis_id] = 0.0 if active is None else np.where(active, weights[axis_id], 0.0)
    return scoped


def _priority_override_mask(values: MaterialColumn, equals: str) -> np.ndarray:
    """0次条件が材料の値のどの要素に当たるか。**一致の判定はここだけが持つ**。

    `equals`は`CategoricalShape.mapping`のキーと同じ読み方をする（"true"/"false"だけを真偽へ読み、
    それ以外は書いたとおりの値の名前）。真偽の材料は1.0/0.0/NaNの数値の配列で届き
    （`material_catalog.material_array_columns`）、真偽との`==`が1.0/0.0と一致する。分類の材料はルート選びでは`CategoricalColumn`で届き、
    語彙の値と比べる。欠損（None・NaN）はどの`equals`にも当たらない。
    """
    if isinstance(values, CategoricalColumn):
        return values.equals(flag_or_value_name(equals))
    return np.asarray(values == flag_or_value_name(equals), dtype=bool)


def _numeric_column(values: Sequence[object]) -> np.ndarray:
    """項の材料の値の並び（欠損=None）を数値の配列へ（真偽は1.0/0.0、欠損はNaN）。項の材料は
    numeric/booleanに限られる（`check_axis_definition`）。"""
    return np.array([np.nan if v is None else float(cast(SupportsFloat, v)) for v in values], dtype=float)


def _value_column(values: Sequence[object]) -> np.ndarray:
    """項以外で読む材料（分類の材料・0次条件の材料）の値の並びを、値のままのobjectの配列へ
    （欠損はNone）。文字列を固定長の文字列の配列にすると、対応表の長いキーが切り詰められる。"""
    column = np.empty(len(values), dtype=object)
    column[:] = list(values)
    return column


def _python_value_columns(
    materials: Mapping[str, Sequence[object]], material_ids: Iterable[str], numeric_ids: Collection[str], length: int
) -> dict[str, np.ndarray]:
    """Pythonの値の並び（欠損=None）を、`evaluate_axis_array`が材料の型ごとに受け取る形の配列へ
    並べ替える。`materials`に無い材料は全要素欠損。"""
    missing: Sequence[object] = [None] * length
    return {
        material_id: (_numeric_column if material_id in numeric_ids else _value_column)(
            materials.get(material_id, missing)
        )
        for material_id in material_ids
    }


def _term_material_ids(definitions: Iterable[AxisDefinition]) -> set[str]:
    return {
        term.material
        for definition in definitions
        if isinstance(definition.shape, BreakpointLinearShape)
        for term in definition.shape.terms
    }


def _scores_or_none(scores: np.ndarray) -> list[float | None]:
    return [None if math.isnan(score) else score for score in scores.tolist()]


def evaluate_axis_values(
    definition: AxisDefinition, materials: Mapping[str, Sequence[object]], length: int
) -> list[float | None]:
    """材料id→Pythonの値の並び（長さ`length`、欠損=None）から、要素ごとの軸の得点を求める
    （評価できない要素はNone）。評価は配列へ並べ替えて`evaluate_axis_array`が行う——入口ごとに
    評価を書くと、区間を押して見える得点とルート選びが使う得点が同じ道で食い違う。

    定義が参照しない材料が含まれていてもよく、参照する材料が無ければ全要素欠損として扱う。
    """
    columns = _python_value_columns(
        materials, definition.materials, _term_material_ids([definition]), length
    )
    return _scores_or_none(evaluate_axis_array(definition, columns))


def evaluate_axes_values(materials: Mapping[str, Sequence[object]], length: int) -> dict[str, list[float | None]]:
    """`evaluate_axis_values`の全軸版。公開軸だけを依存順（`topological_axis_order`）に返す。

    評価できなかった公開軸も、キーを残して値をNoneにする（区間インスペクタの`available=False`・
    合成の分母からの除外がこれを前提にする）。
    """
    evaluated = evaluate_axes_array(_axes_python_value_columns(materials, length), AXIS_DEFINITIONS)
    return {
        axis_id: _scores_or_none(evaluated[axis_id])
        for axis_id in topological_axis_order(AXIS_DEFINITIONS)
        if AXIS_DEFINITIONS[axis_id].is_published
    }


def evaluate_axes_inputs(materials: Mapping[str, Sequence[object]], length: int) -> dict[str, list[object]]:
    """公開軸ごとの、得点へ写す前の値（欠損=None）。折れ点の軸は生値、対応表の軸は引く材料の値。
    形の入力は`evaluate_axes_values`と同じ。

    この値が同じ道は、折れ点・対応表をどう置いても同じ得点になる（0次条件が当たる道を除く）。
    """
    columns = _axes_python_value_columns(materials, length)
    with_axes: dict[str, MaterialColumn] = {**columns, **evaluate_axes_array(columns, AXIS_DEFINITIONS)}
    inputs: dict[str, list[object]] = {}
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        if not definition.is_published:
            continue
        shape = definition.shape
        if isinstance(shape, BreakpointLinearShape):
            inputs[axis_id] = list(_scores_or_none(_breakpoint_raw_value_array(shape, with_axes)))
        else:
            column = with_axes[shape.material]
            assert isinstance(column, np.ndarray)  # Pythonの値の入口は分類の番号の列を作らない
            inputs[axis_id] = [None if isinstance(v, float) and math.isnan(v) else v for v in column.tolist()]
    return inputs


def _axes_python_value_columns(materials: Mapping[str, Sequence[object]], length: int) -> dict[str, np.ndarray]:
    """全軸が読む葉の材料（他の軸を除く）を、`evaluate_axes_array`が受け取る形の配列へ並べ替える。"""
    definitions = AXIS_DEFINITIONS.values()
    leaf_ids = {
        material_id
        for definition in definitions
        for material_id in definition.materials
        if material_id not in AXIS_DEFINITIONS
    }
    return _python_value_columns(materials, leaf_ids, _term_material_ids(definitions), length)


def evaluate_axes_array(
    materials: Mapping[str, MaterialColumn], definitions: dict[str, AxisDefinition]
) -> dict[str, np.ndarray]:
    """`definitions`の全軸を依存順（内部軸→公開軸）で評価し、軸id→得点の辞書を返す。
    評価した軸の得点は、後の軸の材料として読まれる（他の軸を材料にする軸）。
    """
    with_axes: dict[str, MaterialColumn] = dict(materials)
    scores: dict[str, np.ndarray] = {}
    for axis_id in topological_axis_order(definitions):
        scores[axis_id] = with_axes[axis_id] = evaluate_axis_array(definitions[axis_id], with_axes)
    return scores


def _term_values(materials: Mapping[str, MaterialColumn], material_id: str) -> np.ndarray:
    """項の材料の配列。項の材料はnumeric/booleanに限られ（`check_axis_definition`）、分類の材料の列は来ない。"""
    values = materials[material_id]
    if isinstance(values, CategoricalColumn):
        raise TypeError(f"項の材料{material_id}が分類の材料です（項は数値・真偽の材料だけを読む）")
    return values


def _breakpoint_raw_total_array(
    shape: BreakpointLinearShape, materials: Mapping[str, MaterialColumn]
) -> tuple[np.ndarray, np.ndarray]:
    """`terms`の重み付き和（`preprocess`まで適用）と、全termの材料が欠損している要素の
    マスクを返す。折れ点を通す前の値で、`evaluate_axis_array`と`axis_raw_value_array`が
    共有する。"""
    total: np.ndarray | None = None
    all_missing: np.ndarray | None = None
    for term in shape.terms:
        values = _term_values(materials, term.material)
        # 項の材料は数値・真偽とも数値の配列で届き、NaNが欠損を表す。
        missing = np.isnan(values)
        all_missing = missing if all_missing is None else all_missing & missing
        if not term.required:
            values = np.where(missing, 0.0, values)
        contribution = values * term.weight
        total = contribution if total is None else total + contribution
    assert total is not None  # 定義上termsは1件以上
    assert all_missing is not None
    if shape.preprocess == "abs":
        total = np.abs(total)
    return total, all_missing


def axis_raw_value_array(
    definition: AxisDefinition, materials: Mapping[str, MaterialColumn]
) -> np.ndarray | None:
    """折れ点を通す前の生値（欠損=NaN）。`CategoricalShape`の軸はNoneを返す。

    得点（0〜100）は目盛りの引き方に依存する相対評価のため、軸単体では経路の良し悪しを
    判断できない。生値をその単位とともに添えると、他の軸を見ずに判断できる。
    """
    shape = definition.shape
    if not isinstance(shape, BreakpointLinearShape):
        return None
    return _breakpoint_raw_value_array(shape, materials)


def _breakpoint_raw_value_array(shape: BreakpointLinearShape, materials: Mapping[str, MaterialColumn]) -> np.ndarray:
    total, all_missing = _breakpoint_raw_total_array(shape, materials)
    return np.where(all_missing, np.nan, total)


def _breakpoint_score_array(shape: BreakpointLinearShape, total: np.ndarray, all_missing: np.ndarray) -> np.ndarray:
    """折れ点の横軸の値（`_breakpoint_raw_total_array`）から得点（小数1桁、`all_missing`の要素はNaN）。"""
    return np.where(all_missing, np.nan, round_difficulty_array(evaluate_breakpoint_linear(total, shape.breakpoints)))


class ScorePoint(StrictModel):
    """材料の値が、折れ点の横軸でどこに当たり何点になるか。"""

    x: float
    score: float


def first_term_points(shape: BreakpointLinearShape, values: Sequence[float]) -> list[ScorePoint | None]:
    """1つ目の項の材料がそれぞれの値を持ち、ほかの項の材料が無い道の、横軸の値と得点。

    評価と同じ計算（項の合成・欠損の扱い・前処理・折れ線・丸め）で出す。ほかの項に必須の材料が
    あると、評価はその道を欠損にするため、ここもNoneを返す。
    """
    term_ids = [term.material for term in shape.terms]
    columns = _python_value_columns({shape.terms[0].material: values}, term_ids, term_ids, len(values))
    total, all_missing = _breakpoint_raw_total_array(shape, columns)
    xs = _scores_or_none(np.where(all_missing, np.nan, total))
    scores = _scores_or_none(_breakpoint_score_array(shape, total, all_missing))
    return [
        None if x is None or score is None else ScorePoint(x=x, score=score) for x, score in zip(xs, scores)
    ]


def raw_values(shape: "AxisShape", materials: Mapping[str, Sequence[object]], length: int) -> list[float | None]:
    """`axis_raw_value_array`をPythonの値の並び（`evaluate_axis_values`と同じ形）から求める。
    保存前の`shape`も渡せるよう軸の定義ではなく形を受け取る。`CategoricalShape`は全要素None。"""
    if not isinstance(shape, BreakpointLinearShape):
        return [None] * length
    term_ids = [term.material for term in shape.terms]
    columns = _python_value_columns(materials, term_ids, term_ids, length)
    return _scores_or_none(_breakpoint_raw_value_array(shape, columns))


def evaluate_axis_array(definition: AxisDefinition, materials: Mapping[str, MaterialColumn]) -> np.ndarray:
    """材料の配列から要素ごとの軸の得点を求める（欠損=NaN）。軸の評価はこれ1本。

    `materials`は材料id→同じ長さの列（数値・真偽の材料はfloat配列で、真偽は1.0/0.0、
    欠損はNaN。categorical材料はルート選びでは`CategoricalColumn`、Pythonの値の入口では
    dtype=object の配列で欠損はNone）。requiredな材料のNaNは演算で
    自然に伝播し、required=Falseの材料のNaNは0へ置き換えて寄与なしとして扱う。ただし全termの
    材料が欠損している要素はNaN（評価不能）を返す——寄与が1件も無い状態へ「NaNは0とみなす」
    規則を適用すると「材料が1つも観測されていない」ことと「観測した結果が0だった」ことが
    区別できないため。

    `definition.priority_overrides`はshape計算の結果へ後から重ねる
    （`np.where`をpriority_overridesの逆順に重ねることで、定義順で最初に一致した条件が
    最優先になる）。
    """
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape):
        result = _breakpoint_score_array(shape, *_breakpoint_raw_total_array(shape, materials))
    else:
        # CategoricalShape。真偽の材料の1.0/0.0の数値配列は真偽のキーとの一致が同じ答えになるため、
        # キーをfloatへ変えない。
        result = evaluate_categorical(materials[shape.material], shape.mapping)
    for override in reversed(definition.priority_overrides):
        mask = _priority_override_mask(materials[override.material], override.equals)
        result = np.where(mask, override.value, result)
    return result
