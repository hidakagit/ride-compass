"""評価軸が参照する材料（material）の正式カタログ。

`domain/axis_definitions.py: AXIS_DEFINITIONS`の各軸（`MaterialTerm.material`・
`CategoricalShape.material`）が参照する材料idの単一ソース（詳細は
docs/modules/backend/evaluation-scoring.md「材料カタログ」参照）。

**材料の「登録」と「評価軸での利用」は独立している**: MVTタイル
（`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`）には、既存の軸が実際に使う
材料以外にも多くの生データ（highway・surface・smoothness等）が既に焼き込まれている。
設計の一貫性のため、これらも「評価や地図描画に使えそうな生データ」として本カタログへ
網羅的に登録する。登録済みでも対応する軸が無ければ評価には使われない（軸スタジオの
材料選択肢には現れる）。

材料自体はGUIから追加・編集・削除できない（コード変更＋デプロイが前提）。軸スタジオ
（`/admin`）が材料を選ぶ際は、本カタログを`GET /api/material-catalog`経由で動的に取得する
（`api/routers/material_catalog.py`）。新しい材料を増やすときはこのファイルへ1件追加する
だけで、フロントのコード変更・再デプロイなしに軸コンポーザーの選択肢へ現れる。

`tile_property`はMVTタイル（`road_graph_repository.py:
_ROAD_SURFACE_TILE_MVT_SQL`）に既に焼き込まれているプロパティ名（無ければ材料が
タイル非依存＝地図レイヤーのramp自動生成が不可能なことを表す）。`GET /api/material-catalog`
の公開レスポンスには含めない（フロントの軸コンポーザーが必要とするのは`material_id`/
`label`/`dtype`のみで、tileの内部実装詳細を露出させる理由が無いため）——`domain/axis_display.py`が
backend内部でのみこのフィールドを使う。
"""

from dataclasses import dataclass

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.domain.material_sql import (
    BICYCLE_NORMALIZED_SQL,
    LANES_COUNT_CASE_SQL,
    MAXSPEED_KMH_CASE_SQL,
    SMOOTHNESS_NORMALIZED_SQL,
    SURFACE_GOOD_CASE_SQL,
    SURFACE_NORMALIZED_SQL,
    cycleway_has_value_sql,
    landcover_value_sql,
    poi_density_value_sql,
    BRIDGE_NORMALIZED_SQL,
    CYCLEWAY_TAG_NAMES,
    HIGHWAY_SQL,
    LIT_NORMALIZED_SQL,
    MOTOR_VEHICLE_NORMALIZED_SQL,
    TUNNEL_NORMALIZED_SQL,
    normalized_tag_sql,
    tag_is_value_sql,
    tag_absent_is_false_sql,
)
from app.domain.traffic import POI_COUNT_KINDS
from app.domain.wind import WIND_DRAG_REFERENCE_SPEED_MS, wind_drag_ratio
from app.domain.strict_model import StrictModel

Population = Literal["way", "edge"]
# "unknown": 欠損は不明値（NaN/None）として扱われ、その材料を使う軸は評価対象外になる。
# "definite": 欠損は確定値（タグ不在=非該当等）として扱われ、軸は通常どおり評価される。
MissingSemantics = Literal["unknown", "definite"]


@dataclass(frozen=True)
class WayMaterialCoverageSpec:
    """`osm_raw_ways`全行を母集団とする材料。`missing_condition`は`osm_raw_ways`の列・
    JSONB参照のみで構成したSQL真偽式（trueなら欠損）で、外部入力を連結しない。

    `in_scope`は担当バッチが処理できる行の条件。**対象外の行を欠損に数えると、欠損率が
    構造的に0へ到達しない**——運用者は「もう一度流せば0になるはず」と読むが決してならず、
    未実行なのか対象外なのかを画面から区別できない（母集団は全件のままにする。
    `derived_data_freshness.py`の完成度と同じ扱い）。"""

    missing_condition: str
    source: str
    missing_semantics: MissingSemantics
    population: Population = "way"
    in_scope: str = "TRUE"


@dataclass(frozen=True)
class EdgeMaterialCoverageSpec:
    """`road_edges`全行を母集団とする材料。`in_scope`の意味は`WayMaterialCoverageSpec`と同じ。

    `present_count_sql`は「値を持つEdge数」を1行1列で
    返すSELECT文（派生テーブル側だけを数える。FK CASCADEにより行は必ず既存Edgeに対応する）。"""

    present_count_sql: str
    source: str
    missing_semantics: MissingSemantics
    population: Population = "edge"


@dataclass(frozen=True)
class CoverageExcluded:
    """欠損率を測らない材料と、その理由。`MaterialSpec.coverage`が
    `WayMaterialCoverageSpec`/`EdgeMaterialCoverageSpec`とこの型のいずれかを必ず持つため、
    「どちらの一覧にも載っていない材料」は型として作れない。

    測らない材料も`missing_semantics`は持つ。**欠損率を測るかと、値が無いときにどう
    評価するかは別の問い**で、後者は`MaterialSpec.bool_default`が全材料に対して答える
    ——3つの型のうち1つだけがこの宣言を欠くと、そこだけ答えを作り出すことになる。"""

    reason: str
    missing_semantics: MissingSemantics


MaterialCoverage = WayMaterialCoverageSpec | EdgeMaterialCoverageSpec | CoverageExcluded


def _landcover_coverage(key: str) -> EdgeMaterialCoverageSpec:
    """土地被覆1クラスの欠損判定。クラスごとに書き写すと、増えたときここだけ取り残される。

    **値を読む列そのものを数える**（`landcover_value_sql`と同じ`edge_materials.lc_*`）。
    別の表を数えると、値が空でも「揃っている」と報告しうる。列がNULLなのは
    「未計算」か「算出不能（ラスタ範囲外等）」で、どちらも値が無いことに変わりはない。
    """
    return EdgeMaterialCoverageSpec(
        present_count_sql=f"SELECT count(*) FROM edge_materials WHERE lc_{key} IS NOT NULL",
        source=f"edge_materials.lc_{key}（derive_raster_materialsの計算済み値）の有無",
        missing_semantics="unknown",
    )

_CYCLEWAY_TAGS_ALL_ABSENT = " AND ".join(f"tags->>'{tag}' IS NULL" for tag in CYCLEWAY_TAG_NAMES)
_CYCLEWAY_SOURCE = "osm_raw_ways.tags の cycleway / cycleway:left / cycleway:right / cycleway:both（いずれも無い場合に欠損）"
_EDGE_COUNTS_PRESENT_SQL = ("SELECT count(*) FROM edge_materials WHERE intersection_count IS NOT NULL")
_EDGE_COUNTS_SOURCE = "edge_materialsの数の列が埋まっているか"


MaterialDType = Literal["numeric", "boolean", "categorical"]


class MaterialReferencePoint(StrictModel):
    """軸スタジオの折れ点編集を助ける「値の目安」1点。材料の値域が
    直感的でない場合（風の材料等）に、換算式を知らなくても代表的な状況がどの値になるかを
    示す。換算式自体はbackendだけが持ち、値はここで計算済みのものを持たせる
    （design-principles.md構造仕様1、
    frontendはこの一覧をそのまま表示するのみ）。"""

    #: 値は有限（`allow_inf_nan=False`）。NaN・infが混ざると軸スタジオの入力欄がその1件で
    #: 壊れ、空ラベルは並んでいても意味を持たない。
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    label: str = Field(min_length=1)
    value: float


class MaterialSpec(StrictModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    material_id: str
    label: str
    # GET /api/material-catalogの公開レスポンスへ含め、
    # フロント側は選択中の材料の隣に情報アイコン(ⓘ)でこの説明文を表示する（AxisComposer.tsx:
    # MaterialInfoButton）。`value_sql`を持たない材料は、選んでも評価軸としては機能しない
    # 旨をここに明記する（配線状況が変わったら追従が必要）。
    # 空を許すと、軸スタジオのⓘが何も出さない材料を登録できてしまう。
    description: str = Field(min_length=1)
    dtype: MaterialDType
    # 値の単位（凡例・数値表示用の表記、無次元・真偽値・カテゴリ値は空文字）。地図の凡例が
    # 材料の生値を表示するときの単位の唯一の正（frontendは単位を持たない）。
    unit: str = ""
    # 同じ単位の他の材料と**足し合わせて意味を持つ量**か（示量／示強の区別）。回・件・個の
    # ような個数と、それを同じ距離で割った密度（回/km等）は足せる。%・km/h・倍率のような
    # 割合・率は、母数の違うものを足しても何も表さないためFalseのまま。
    # domain/axis_raw_value.py: raw_value_unitは、2項以上の重み付き和の生値を利用者へ見せて
    # よいかの判定にこれを使う（単位が揃っているだけでは和の意味は保証されない）。
    additive: bool = False
    # 距離を掛けた総量（例: 「0.8回/km」→「約26回」）を出すときの単位。**総量が読み手の
    # 判断を変える量にだけ置く**——回・件のように数えられる出来事は「この経路で何回止まるか」
    # を答えるが、角度のような連続量は総量（「約3322度曲がる」）を出しても比べる尺度が無い。
    # `additive`（足し合わせて意味を持つか）とは別の問い: 事故密度は足せるが、総量は読めない。
    # 単位が「◯◯/km」であることだけを条件にすると、この区別が付かない。
    total_unit: str | None = None
    # MVTタイルへ既に焼き込み済みのプロパティ名。Noneは「タイル非依存」（GSI標高の都度取得、
    # 気象の動的取得、レシピ合成値等）で、地図レイヤーのramp自動生成対象になりえない。
    tile_property: str | None = None
    # tile_propertyの生値と材料の値がスケール不一致（実行時に変動する係数での
    # 変換が必要）な場合True。例: accident_count_per_km_yearは収録年数（実行時にDBから
    # 取得、増え続ける）で正規化済みだが、tile_propertyのaccident_per_kmは年正規化前の生値。
    # 静的な変換係数を持てないため、地図表示の導出は閾値を安全に流用できない。
    tile_property_needs_runtime_scale: bool = False
    # 材料の値が進行方向によって変わる（有向）場合True。地図のrampレイヤーは
    # 1本の線を単色で塗る前提のため、方向依存材料は単純な重み付き和で表現できない
    # （時間依存の風レイヤー・降水ナウキャストと同じく、矢印等の専用表示が別途必要）。
    # 方向で値が変わる材料は方向を持たないMVTプロパティへ焼き込めないため、
    # `tile_property=None`と両輪で「この材料はramp化しない」を宣言する。
    tile_property_direction_dependent: bool = False
    # この材料の由来となる一次属性id（domain/registry.py:
    # PrimaryAttributeSpec.attr_id、frontend側はprimaryAttributes.ts:
    # PRIMARY_ATTRIBUTE_LAYER_IDS/PRIMARY_ATTRIBUTE_CHIP_LABELSのキー）。材料id（例:
    # bicycle_infra・maxspeed_kmh・poi_signal_per_km）と一次属性id（例: cycleway・
    # maxspeed・stop_poi）は名前が異なる別の名前空間のため、対応が自明でない材料には
    # 明示的にここへ書く。Noneは「対応する一次属性が無い」（動的データ由来のwind_drag_ratio、
    # 一次属性未登録のbridge/smoothness等）。GET /api/axis-catalogが軸ごとにこれを解決して
    # 返すことで、frontend側（axisMaterialLayerIds、MapOverlayControls.tsxの材料一覧表示）が
    # 軸スタジオ作成軸に対しても同じ仕組みで動く。
    primary_attribute_id: str | None = None
    # この材料の値をDBから求めるSQL式。読み出し側（`road_graph_repository.py`）が
    # エイリアス（区間なら`re`/`c`/`e`/`el`/`wl`/`d`、wayなら同名の別ソース）を用意し、
    # この式をそのまま並べる。Noneは「SQLでは求められない」——リクエスト時に決まる風、
    # 評価へ配線していないDEFER材料。**材料の値の求め方をここ以外へ書かない**
    # （設計原則 構造仕様8。別の辞書へ分けると、材料を増やしたとき片方が取り残される）。
    value_sql: str | None = None
    # 欠損率の測り方（`/admin`の材料タブ）。`CoverageExcluded`を含む3択で、**どれかを必ず
    # 持つ**——「どちらの一覧にも載っていない材料」を型として作れなくする。中身は
    # `value_sql`から導けない（「値がいくつか」と「元データがあるか」は別の問い。
    # 例: `lit`の値は欠損をfalseへ畳むが、欠損率はタグの有無を数える）。
    coverage: MaterialCoverage
    # 材料の値（OSMタグ生値）ごとの日本語ラベル対訳表（タグ値→ラベル）。
    # highway/surface/smoothnessのようなオープンエンドな多値材料だけが持つ（他は空dict）。
    # 軸スタジオ（AxisComposer.tsx）の「値の候補」セレクトが`GET /api/material-catalog/
    # {material_id}/values`経由で表示するラベルの単一ソース。値の意味は材料そのものの
    # 定義に属するドメイン知識のため、他のフィールドと同じくここ（MaterialSpec自体）へ
    # 一元化する（material_id文字列をキーにした別の並列辞書にすると、材料の追加・削除の
    # たびに2箇所を同期する必要が生じるリスクを持ち込むため避ける）。
    value_labels: dict[str, str] = {}
    # 軸スタジオの折れ点編集を助ける「値の目安」一覧（`MaterialReferencePoint`）。
    # 値域が直感的でない材料（風等）ほど有用なため全材料必須ではなく、真偽値・categorical
    # 材料や単純な材料は空のままでよい。
    reference_points: list[MaterialReferencePoint] = []

    def value_label(self, value: str) -> str:
        """タグ生値から「論理名 - 物理名」形式の表示用ラベルを組み立てる
        （例: "自転車専用道 - cycleway"）。対訳表に無い値は物理名のみ返す
        （フォールバック、新しいOSMタグ値がDBに現れてもAPIが失敗しないようにするため。
        この場合論理名が無いため" - "を付けない）。"""
        label = self.value_labels.get(value)
        if label is None:
            return value
        return f"{label} - {value}"

    def full_label(self) -> str:
        """材料名を「論理名 - 物理名」形式の表示用ラベルにする（例: "道路種別 - highway"、
        value_labelと同じ理由で軸スタジオの材料選択肢に物理名[material_id]を併記する）。"""
        return f"{self.label} - {self.material_id}"

    @model_validator(mode="after")
    def _check_fields_match_the_dtype(self) -> "MaterialSpec":
        """dtypeと噛み合わない宣言を登録時に落とす。通すと、その材料を選んだ画面だけが
        黙って何も出さない（値の目安が空の折れ点編集、対訳の効かない値の候補）。"""
        if self.total_unit is not None and not self.unit:
            # 総量は生値へ距離を掛けた量で、単位の無い材料には掛ける相手が無い
            # （`axis_raw_value.py: raw_value_total_unit`は`unit`が空の軸を先に落とす）。
            raise ValueError(f"{self.material_id}: total_unitはunitを持つ材料にだけ置ける")
        if self.value_labels and self.dtype != "categorical":
            raise ValueError(f"{self.material_id}: value_labelsはcategorical材料の値にだけ付く")
        if self.reference_points and self.dtype != "numeric":
            raise ValueError(f"{self.material_id}: reference_pointsは数値材料の折れ点編集にだけ効く")
        return self


    @property
    def bool_default(self) -> Literal["false", "nan"]:
        """欠損を配列上どう持つか。**宣言は`coverage`1つにする**——2か所に置くと、片方だけ
        書き換えたときに画面と評価が食い違い、どちらが正しいかを誰も保証しない。

        bool配列とfloat配列は数値的に等価ではない（`axis_definitions.py:
        evaluate_axis_array`が`values.dtype == bool`で分岐する）。
        """
        if self.dtype != "boolean":
            return "false"  # bool配列を作らない材料では参照されない
        return "nan" if self.coverage.missing_semantics == "unknown" else "false"

def _wind_drag_ratio_reference_points() -> list[MaterialReferencePoint]:
    """`wind_drag_ratio`材料の参考点（時速20km=基準速度で走行、走行方位0度を基準に
    風向差0度=向かい風・180度=追い風・90度=真横として`wind_drag_ratio`で計算する）。"""
    v = WIND_DRAG_REFERENCE_SPEED_MS
    scenarios = [
        ("時速20km・向かい風2m/s", 2.0, 0.0),
        ("時速20km・向かい風4m/s", 4.0, 0.0),
        ("時速20km・向かい風8m/s", 8.0, 0.0),
        ("時速20km・追い風4m/s", 4.0, 180.0),
        ("時速20km・真横4m/s", 4.0, 90.0),
        ("走行速度と同じ追い風", v, 180.0),
    ]
    return [
        MaterialReferencePoint(label=label, value=round(wind_drag_ratio(wind_speed_ms, wind_direction_deg, 0.0, v), 2))
        for label, wind_speed_ms, wind_direction_deg in scenarios
    ]


_GRADIENT_PERCENT_REFERENCE_POINTS = [
    MaterialReferencePoint(label="平坦", value=0.0),
    MaterialReferencePoint(label="緩い坂", value=3.0),
    MaterialReferencePoint(label="きつい坂", value=9.0),
    MaterialReferencePoint(label="激坂", value=15.0),
]

_POI_COUNT_PER_KM_REFERENCE_POINTS = [
    MaterialReferencePoint(label="少ない", value=0.5),
    MaterialReferencePoint(label="普通", value=2.0),
    MaterialReferencePoint(label="多い", value=5.0),
]

# 目安の値（軸スタジオの材料選択で「この材料はどのくらいの値を取るか」を示す代表点）。

_INTERSECTION_COUNT_PER_KM_REFERENCE_POINTS = [
    MaterialReferencePoint(label="少ない", value=1.0),
    MaterialReferencePoint(label="普通", value=3.0),
    MaterialReferencePoint(label="多い", value=8.0),
]

_ACCIDENT_COUNT_PER_KM_YEAR_REFERENCE_POINTS = [
    MaterialReferencePoint(label="少ない", value=0.02),
    MaterialReferencePoint(label="普通", value=0.1),
    MaterialReferencePoint(label="多い", value=0.3),
]

_MAXSPEED_KMH_REFERENCE_POINTS = [
    MaterialReferencePoint(label="生活道路", value=20.0),
    MaterialReferencePoint(label="一般道", value=40.0),
    MaterialReferencePoint(label="幹線道路", value=60.0),
    MaterialReferencePoint(label="高規格道路", value=80.0),
]

_LANES_COUNT_REFERENCE_POINTS = [
    MaterialReferencePoint(label="1車線", value=1.0),
    MaterialReferencePoint(label="2車線", value=2.0),
    MaterialReferencePoint(label="4車線以上", value=4.0),
]


# 材料の値（OSMタグ生値）ごとの日本語ラベル対訳表。
# MaterialSpec.value_labelsのdocstring参照——「地図表示と評価は別」という方針に基づき、
# 地図の絞り込みUI（components/Map/roadFilterAxes.ts: HIGHWAY_GROUPS/SURFACE_GROUPS、
# 意図的に多対一）とは独立した1値1ラベルの専用対訳表。各値の日本語ラベルはOSM wiki
# （Key:highway/Key:surface）の一般的なタグ定義に基づく。MaterialSpecの呼び出し直下へ
# インラインで書くと材料定義ブロックの見通しが悪くなるためここへ分けているだけで、
# 値は`value_labels=`で各MaterialSpecへそのまま渡す。材料をまたぐ別辞書ではない。
_HIGHWAY_VALUE_LABELS: dict[str, str] = {
    "motorway": "高速道路",
    "motorway_link": "高速道路の連絡路",
    "trunk": "幹線道路",
    "trunk_link": "幹線道路の連絡路",
    "primary": "主要幹線道路",
    "primary_link": "主要幹線道路の連絡路",
    "secondary": "地方主要道",
    "secondary_link": "地方主要道の連絡路",
    "tertiary": "地方道",
    "tertiary_link": "地方道の連絡路",
    "unclassified": "未区分の道路",
    "residential": "住宅街の道路",
    "living_street": "生活道路（歩車共存）",
    "service": "施設内通路",
    "road": "種別不明の道路",
    "cycleway": "自転車専用道",
    "path": "小道・遊歩道",
    "footway": "歩道",
    "pedestrian": "歩行者専用道路",
    "bridleway": "乗馬道",
    "steps": "階段",
    "track": "農道・林道",
}

_SURFACE_VALUE_LABELS: dict[str, str] = {
    "asphalt": "アスファルト",
    "paved": "舗装（種別不明）",
    "chipseal": "チップシール舗装",
    "concrete": "コンクリート",
    "concrete:plates": "コンクリート版",
    "concrete:lanes": "コンクリート帯（轍部のみ舗装）",
    "paving_stones": "石畳（切石）",
    "sett": "石畳（玉石）",
    "cobblestone": "玉石舗装",
    "unhewn_cobblestone": "玉石舗装（未加工）",
    "bricks": "レンガ舗装",
    "gravel": "砂利",
    "fine_gravel": "細砂利",
    "compacted": "締固め砂利",
    "pebblestone": "小石敷き",
    "rock": "岩盤",
    "unpaved": "未舗装（種別不明）",
    "dirt": "土",
    "ground": "地面（土・砂利混合）",
    "earth": "土（地表面）",
    "mud": "泥",
    "sand": "砂",
    "grass": "芝・草地",
    "woodchips": "ウッドチップ",
}

_SMOOTHNESS_VALUE_LABELS: dict[str, str] = {
    "excellent": "非常に良好（ロードバイク推奨）",
    "good": "良好",
    "intermediate": "普通",
    "bad": "悪い",
    "very_bad": "かなり悪い",
    "horrible": "劣悪",
    "very_horrible": "極めて劣悪",
    "impassable": "通行不能",
}


#: 一次属性のラベル（材料が指す先の表示名）。ここに無い一次属性を材料が指すと、
#: レジストリ登録の時点で落ちる。
PRIMARY_ATTRIBUTE_LABELS: dict[str, str] = {
    "highway": "道路の種類",
    "lanes": "車線数",
    "maxspeed": "制限速度",
    "cycleway": "自転車インフラ",
    "surface": "路面の種類",
    "motor_vehicle_access": "自動車通行可否",
    "lit": "街灯",
    "tunnel": "トンネル",
    "oneway": "一方通行",
    "elevation": "標高",
    "stop_poi": "停止要因",
    "accident_point": "事故地点",
    "intersection": "交差点",
    "landcover": "土地被覆",
}

#: 材料を1つも持たない一次属性。`inputs`は材料から導出されるため、どの軸からも参照されず
#: 評価に効かない——地図レイヤーの分類としてだけ存在する。
PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL: dict[str, str] = {
    "supply_poi": "補給・休憩ポイント",
}


# 軸が参照する材料と、MVTタイルへ焼き込み済みだが評価軸には未使用の生データの両方を持つ
# （モジュール冒頭の注記参照）。
MATERIAL_CATALOG: dict[str, MaterialSpec] = {
    "gradient_percent": MaterialSpec(
        material_id="gradient_percent",
        label="勾配（符号付き）",
        description="国土地理院の標高データから算出した進行方向の勾配（%）。登り坂はプラス、下り坂はマイナスです。",
        dtype="numeric",
        unit="%",
        # 進行方向で符号が変わる（登りプラス・下りマイナス）ため、1本のWayに往復2つの値を
        # 持ちうる。方向を持たないMVTプロパティ1個には焼き込めないので、地図へは
        # `services/gradient_way_service.py`のway_id→値配信で乗せる。
        tile_property=None,
        tile_property_direction_dependent=True,
        primary_attribute_id="elevation",
        reference_points=_GRADIENT_PERCENT_REFERENCE_POINTS,
        value_sql="em.average_grade",
        coverage=EdgeMaterialCoverageSpec(
                present_count_sql="SELECT count(*) FROM edge_materials WHERE average_grade IS NOT NULL",
                source="edge_materials.average_grade の有無",
                missing_semantics="unknown",
            ),
    ),
    "wind_drag_ratio": MaterialSpec(
        material_id="wind_drag_ratio",
        label="風の追加負荷(倍率)",
        description=(
            "出発時刻の気象予報・ルートの進行方向・想定速度から、相対風速の二乗則で求めた空気抵抗の増分"
            "（時速20kmで無風のときの空気抵抗を1とする倍率）。プラス=向かい風で重くなる、マイナス=追い風で楽になる、"
            "真横の風は小さなプラス。同じ風でも速く走るほど値が大きくなります。"
            "目安（時速20km）: 向かい風2m/s→0.85、4m/s→1.96、8m/s→4.95、追い風4m/s→-0.92、真横4m/s→0.23、"
            "走行速度と同じ追い風→-1.0。"
        ),
        dtype="numeric",
        # 気象は動的データ（出発時刻依存）のためタイルに焼き込めない（`domain/wind.py:
        # wind_drag_ratio_array`がリクエスト時に計算する）。対応する一次属性も未登録
        # （動的気象は一次属性レジストリの対象外）。
        tile_property=None,
        tile_property_direction_dependent=True,
        reference_points=_wind_drag_ratio_reference_points(),
        coverage=CoverageExcluded(
            reason="出発時刻の気象予報・想定速度から都度計算する動的材料で、DBに静的な値を持たない",
            missing_semantics="unknown",
        ),
    ),
    "trees_percent": MaterialSpec(
        material_id="trees_percent",
        label="樹木被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の樹木被覆の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="trees_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("trees"),
        coverage=_landcover_coverage("trees"),
    ),
    "built_percent": MaterialSpec(
        material_id="built_percent",
        label="建物被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の建物被覆の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="built_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("built"),
        coverage=_landcover_coverage("built"),
    ),
    "crops_percent": MaterialSpec(
        material_id="crops_percent",
        label="農地被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の農地の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="crops_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("crops"),
        coverage=_landcover_coverage("crops"),
    ),
    "rangeland_percent": MaterialSpec(
        material_id="rangeland_percent",
        label="草地被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の草地の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="rangeland_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("rangeland"),
        coverage=_landcover_coverage("rangeland"),
    ),
    "water_percent": MaterialSpec(
        material_id="water_percent",
        label="水面被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の水面の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="water_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("water"),
        coverage=_landcover_coverage("water"),
    ),
    "bare_percent": MaterialSpec(
        material_id="bare_percent",
        label="裸地被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の裸地（河川敷・造成地等）の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="bare_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("bare"),
        coverage=_landcover_coverage("bare"),
    ),
    "flooded_veg_percent": MaterialSpec(
        material_id="flooded_veg_percent",
        label="湿地被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の湿地（冠水植生）の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="flooded_veg_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("flooded_veg"),
        coverage=_landcover_coverage("flooded_veg"),
    ),
    "snow_ice_percent": MaterialSpec(
        material_id="snow_ice_percent",
        label="雪氷被覆率",
        description="衛星画像の土地被覆データ（Esri×Impact Observatory）から算出した、道路周囲100mリング内の雪氷の割合(%)。",
        dtype="numeric",
        unit="%",
        tile_property="snow_ice_pct",
        primary_attribute_id="landcover",
        value_sql=landcover_value_sql("snow_ice"),
        coverage=_landcover_coverage("snow_ice"),
    ),
    "surface_good": MaterialSpec(
        material_id="surface_good",
        label="舗装良否",
        description="OSMの路面タグ(surface)から判定した舗装の良否。true=舗装良好、false=未舗装等。",
        dtype="boolean",
        tile_property="surface_good",
        primary_attribute_id="surface",
        value_sql=SURFACE_GOOD_CASE_SQL,
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"({SURFACE_GOOD_CASE_SQL}) IS NULL",
                source="osm_raw_ways.surface（良否いずれの分類にも該当しない値も欠損に含む）",
                missing_semantics="unknown",
            ),
    ),
    "intersection_count_per_km": MaterialSpec(
        material_id="intersection_count_per_km",
        label="交差点密度",
        description="接続する道路が3本以上ある交差点の1kmあたりの発生回数。",
        dtype="numeric",
        unit="回/km",
        additive=True,
        total_unit="回",
        tile_property="intersection_per_km",
        primary_attribute_id="intersection",
        reference_points=_INTERSECTION_COUNT_PER_KM_REFERENCE_POINTS,
        value_sql="CASE WHEN re.distance_m > 0 THEN em.intersection_count / (re.distance_m / 1000.0) END",
        coverage=EdgeMaterialCoverageSpec(
                present_count_sql=_EDGE_COUNTS_PRESENT_SQL,
                source=_EDGE_COUNTS_SOURCE,
                missing_semantics="unknown",
            ),
    ),
    "accident_count_per_km_year": MaterialSpec(
        material_id="accident_count_per_km_year",
        label="事故密度",
        description="警察庁の事故データに基づく、1kmあたり・1年あたりの人身事故件数。",
        dtype="numeric",
        unit="件/(km・年)",
        additive=True,
        # タイル側は年正規化前の"accident_per_km"（収録全年分の重み付き件数/km）。
        # 年正規化はAXIS_DEFINITIONS側の評価ロジックが行うため、ramp化する場合は
        # 閾値をタイル側のスケールへ再換算する必要がある。収録年数は実行時にDBから
        # 取得し増え続けるため、静的な変換係数を持てない（registry_defaults.pyの
        # 既存accident表示は手書きのまま維持する）。
        tile_property="accident_per_km",
        tile_property_needs_runtime_scale=True,
        primary_attribute_id="accident_point",
        reference_points=_ACCIDENT_COUNT_PER_KM_YEAR_REFERENCE_POINTS,
        value_sql="CASE WHEN re.distance_m > 0 AND :accident_years > 0 "
        "THEN em.accident_count / (re.distance_m / 1000.0) / :accident_years END",
        coverage=EdgeMaterialCoverageSpec(
                present_count_sql=_EDGE_COUNTS_PRESENT_SQL,
                source=_EDGE_COUNTS_SOURCE,
                missing_semantics="unknown",
            ),
    ),
    "lit": MaterialSpec(
        material_id="lit",
        label="街灯あり",
        description="OSMの街灯タグ(lit=yes)に該当する区間はtrue。タグ不在はfalse（街灯なし扱い）。",
        dtype="boolean",
        tile_property="lit",
        primary_attribute_id="lit",
        value_sql=tag_is_value_sql("lit", "yes"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{LIT_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.tags->>'lit'（タグ不在は街灯なし扱い）",
                missing_semantics="definite",
            ),
    ),
    "has_tunnel": MaterialSpec(
        material_id="has_tunnel",
        label="トンネル",
        description="OSMのトンネルタグ(tunnel=yes)に該当する区間はtrue。",
        dtype="boolean",
        tile_property="tunnel",
        primary_attribute_id="tunnel",
        value_sql=tag_is_value_sql("tunnel", "yes"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{TUNNEL_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.tags->>'tunnel'（タグ不在は非該当扱い）",
                missing_semantics="definite",
            ),
    ),
    # --- MVTタイルに焼き込み済みだが評価軸には未使用の生データ ---
    "bridge": MaterialSpec(
        material_id="bridge",
        label="橋・高架",
        description="OSMの橋・高架タグ(bridge=yes)に該当する区間はtrue。",
        dtype="boolean",
        # OSMのbridgeタグ（yesのみtrue、それ以外はキー省略＝unknown/false扱い）。
        tile_property="bridge",
        value_sql=tag_is_value_sql("bridge", "yes"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{BRIDGE_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.tags->>'bridge'（タグ不在は非該当扱い）",
                missing_semantics="definite",
            ),
    ),
    "motor_vehicle_no": MaterialSpec(
        material_id="motor_vehicle_no",
        label="自動車通行不可",
        description="OSMのタグ(motor_vehicle=no)から判定した、自動車が通行できない区間かどうか。",
        dtype="boolean",
        # OSMのmotor_vehicleタグがnoの区間（内部軸
        # [domain/axis_definitions.py]でも参照される材料だが、軸合成前の生の真偽値自体は
        # 独立して材料登録していなかった）。
        tile_property="motor_vehicle_no",
        primary_attribute_id="motor_vehicle_access",
        value_sql=tag_is_value_sql("motor_vehicle", "no"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{MOTOR_VEHICLE_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.tags->>'motor_vehicle'（タグ不在は通行可扱い）",
                missing_semantics="definite",
            ),
    ),
    "oneway": MaterialSpec(
        material_id="oneway",
        label="一方通行",
        description="OSMのタグから判定した一方通行区間かどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用）。",
        dtype="boolean",
        # 値の求め方を持たない（`value_sql=None`）: 元になるosm_raw_ways.directionは
        # build_road_graphがforward/backward Edgeを作れるかの判定に消費するだけで、
        # Edgeにも区間の材料列にも残らない。地図表示専用の材料。
        tile_property="oneway",
        primary_attribute_id="oneway",
        coverage=CoverageExcluded(
            reason="osm_raw_ways.directionはNOT NULL列で、タグ不在は双方向(both)に解決済み（欠損の概念が無い）",
            missing_semantics="definite",
        ),
    ),
    "maxspeed_kmh": MaterialSpec(
        material_id="maxspeed_kmh",
        label="制限速度",
        description="OSMの制限速度タグ(maxspeed)から解析した制限速度（km/h）。",
        dtype="numeric",
        unit="km/h",
        tile_property="maxspeed_kmh",
        primary_attribute_id="maxspeed",
        reference_points=_MAXSPEED_KMH_REFERENCE_POINTS,
        value_sql=MAXSPEED_KMH_CASE_SQL,
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"({MAXSPEED_KMH_CASE_SQL}) IS NULL",
                source="osm_raw_ways.tags->>'maxspeed'（数値として解釈できない値も欠損に含む）",
                missing_semantics="unknown",
            ),
    ),
    "lanes_count": MaterialSpec(
        material_id="lanes_count",
        label="車線数",
        description="OSMの車線数タグ(lanes)から解析した車線数。",
        dtype="numeric",
        tile_property="lanes_count",
        primary_attribute_id="lanes",
        reference_points=_LANES_COUNT_REFERENCE_POINTS,
        value_sql=LANES_COUNT_CASE_SQL,
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"({LANES_COUNT_CASE_SQL}) IS NULL",
                source="osm_raw_ways.tags->>'lanes'（数値として解釈できない値も欠損に含む）",
                missing_semantics="unknown",
            ),
    ),
    "highway": MaterialSpec(
        material_id="highway",
        label="道路種別",
        description="OSMの道路種別タグ(highway)の生値（例: residential/primary/cycleway等）。値ごとに個別のスコアを設定できます。",
        dtype="categorical",
        # OSMのhighwayタグ生値（motorway/trunk/primary/secondary/tertiary/residential/
        # living_street/unclassified/track/cycleway/path/footway等）。取込プロファイル
        # （batch/import_profile.yamlのhighway許可リスト）で許可された値のみ実際に現れる。
        # 正準の閉じた値集合はこのプロジェクトで管理していない（OSMタグの生値のため）。
        tile_property="highway",
        primary_attribute_id="highway",
        value_labels=_HIGHWAY_VALUE_LABELS,
        value_sql=HIGHWAY_SQL,
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{HIGHWAY_SQL} IS NULL",
                source="osm_raw_ways.highway",
                missing_semantics="unknown",
            ),
    ),
    "surface": MaterialSpec(
        material_id="surface",
        label="路面種別",
        description="OSMの路面種別タグ(surface)の生値（例: asphalt/gravel等）。良否(舗装良否)だけでなく種別ごとに細かくスコアを設定したい場合に使います。",
        dtype="categorical",
        # OSMのsurfaceタグ生値（正規化: lower/btrim）。良否の正準分類は
        # domain/road.py: GOOD_OSM_SURFACE_TAGS/BAD_OSM_SURFACE_TAGS参照（本材料は
        # その分類前の生タグ値そのもの。分類後の真偽値は既存材料surface_good）。
        tile_property="surface",
        primary_attribute_id="surface",
        value_labels=_SURFACE_VALUE_LABELS,
        value_sql=SURFACE_NORMALIZED_SQL,
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{SURFACE_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.surface",
                missing_semantics="unknown",
            ),
    ),
    # 自転車インフラの分類を、評価軸ではなく材料の側で正規化したフラグ群。軸はこれらを
    # 重み付き線形結合するだけで、タグの読み方を知らない。それぞれ専用のtile_propertyを
    # 持ち、MVTタイルへ焼き込む。
    "highway_is_cycleway": MaterialSpec(
        material_id="highway_is_cycleway",
        label="道路種別が自転車道",
        description="道路種別(highway)自体が自転車道(cycleway)かどうか。",
        dtype="boolean",
        tile_property="highway_is_cycleway",
        # 判定式はhighway生タグを見るが、意味的にはこの群の他の材料と同じ「自転車走行環境の
        # 分類」という1つのまとまりのため、cycleway_has_track等と同じ
        # primary_attribute_id="cycleway"へ寄せる（highway自体は別の軸が
        # 単独で使う一次属性のまま、排他チェック対象を維持する）。
        primary_attribute_id="cycleway",
        value_sql=tag_absent_is_false_sql(f"{HIGHWAY_SQL} = 'cycleway'"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{HIGHWAY_SQL} IS NULL",
                source="osm_raw_ways.highway",
                missing_semantics="definite",
            ),
    ),
    "cycleway_has_track": MaterialSpec(
        material_id="cycleway_has_track",
        label="自転車道(track)を併設",
        description="車道と分離された自転車道(cycleway=track)を併設しているかどうか。",
        dtype="boolean",
        tile_property="cycleway_has_track",
        primary_attribute_id="cycleway",
        value_sql=cycleway_has_value_sql("track"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=_CYCLEWAY_TAGS_ALL_ABSENT,
                source=_CYCLEWAY_SOURCE,
                missing_semantics="definite",
            ),
    ),
    "cycleway_has_lane": MaterialSpec(
        material_id="cycleway_has_lane",
        label="自転車レーン(lane)を併設",
        description="車道上に線で区切られた自転車レーン(cycleway=lane)を併設しているかどうか。",
        dtype="boolean",
        tile_property="cycleway_has_lane",
        primary_attribute_id="cycleway",
        value_sql=cycleway_has_value_sql("lane"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=_CYCLEWAY_TAGS_ALL_ABSENT,
                source=_CYCLEWAY_SOURCE,
                missing_semantics="definite",
            ),
    ),
    "cycleway_has_shared": MaterialSpec(
        material_id="cycleway_has_shared",
        label="バス共用等の自転車レーンを併設",
        description="バス専用レーン共用など、簡易な自転車レーン(cycleway=share_busway/shared_lane)を併設しているかどうか。",
        dtype="boolean",
        tile_property="cycleway_has_shared",
        primary_attribute_id="cycleway",
        value_sql=cycleway_has_value_sql("share_busway", "shared_lane"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=_CYCLEWAY_TAGS_ALL_ABSENT,
                source=_CYCLEWAY_SOURCE,
                missing_semantics="definite",
            ),
    ),
    "shared_pedestrian_path": MaterialSpec(
        material_id="shared_pedestrian_path",
        label="歩行者自転車共用道",
        description="車道と分離された歩行者道のうち、自転車の通行が認められている区間（河川敷サイクリングロード等、highway=footway/pathかつbicycle=yes/designated）かどうか。",
        dtype="boolean",
        tile_property="shared_pedestrian_path",
        primary_attribute_id="cycleway",
        value_sql=tag_absent_is_false_sql(
            f"{HIGHWAY_SQL} IN ('footway', 'path') "
            f"AND {BICYCLE_NORMALIZED_SQL} IN ('yes', 'designated')"
        ),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{BICYCLE_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.tags->>'bicycle'（highway=footway/pathとの組み合わせで判定、タグ不在は非該当扱い）",
                missing_semantics="definite",
            ),
    ),
    "smoothness": MaterialSpec(
        material_id="smoothness",
        label="路面の状態",
        description="OSMの路面状態タグ(smoothness)の生値（excellent〜impassable）。同じ路面種別(surface)でも実際の荒れ具合を区別したい場合に使います。",
        dtype="categorical",
        # OSMのsmoothnessタグ生値（excellent/good/intermediate/bad/very_bad/horrible/
        # very_horrible/impassable、正規化: lower/btrim）。surfaceが路面「種別」なのに
        # 対し、smoothnessは実際の走行感（同じasphaltでも荒れ具合が違う等）。
        tile_property="smoothness",
        value_labels=_SMOOTHNESS_VALUE_LABELS,
        value_sql=SMOOTHNESS_NORMALIZED_SQL,
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{SMOOTHNESS_NORMALIZED_SQL} IS NULL",
                source="osm_raw_ways.tags->>'smoothness'",
                missing_semantics="unknown",
            ),
    ),
    # tracktypeはOSMの未舗装路面グレード（grade1[良好]〜grade5[粗悪]）。MVTタイルへは
    # 焼き込んでいないため（`tile_property=None`）地図には出ず、評価軸の材料としてだけ使える。
    "tracktype": MaterialSpec(
        material_id="tracktype",
        label="未舗装路グレード(tracktype)",
        description="OSMの未舗装路グレードタグ(tracktype)の生値（grade1[良好]〜grade5[粗悪]）。",
        dtype="categorical",
        tile_property=None,
        value_sql=normalized_tag_sql("tracktype"),
        coverage=WayMaterialCoverageSpec(
                missing_condition=f"{normalized_tag_sql('tracktype')} IS NULL",
                source="osm_raw_ways.tags->>'tracktype'",
                missing_semantics="unknown",
            ),
    ),
    # --- 停止要因POIの種別別密度。`domain/traffic.py: POI_COUNT_KINDS`から生成する ---
    # 材料を1件ずつ手書きせず一覧から作るため、キーを増やすときに触るのはその一覧だけで済む。
    # タイル側のプロパティ名も同じ規則で生成しており（`_POI_TILE_COLUMNS_SQL`）、材料idと
    # 一致するため地図のramp自動導出がそのまま効く。
    **{
        f"poi_{kind}_per_km": MaterialSpec(
            material_id=f"poi_{kind}_per_km",
            label=f"{label}の密度",
            description=f"進行する道路上にある{label}の、1kmあたりの数。",
            dtype="numeric",
            unit="回/km",
            additive=True,
            total_unit="回",
            tile_property=f"poi_{kind}_per_km",
            value_sql=poi_density_value_sql(kind),
            # 行があれば載っていないキーは0件と確定できる（欠損は行そのものの不在だけ）。
            coverage=EdgeMaterialCoverageSpec(
                present_count_sql=_EDGE_COUNTS_PRESENT_SQL,
                source=_EDGE_COUNTS_SOURCE,
                missing_semantics="unknown",
            ),
            primary_attribute_id="stop_poi",
            reference_points=_POI_COUNT_PER_KM_REFERENCE_POINTS,
        )
        for kind, label in POI_COUNT_KINDS.items()
    },
}



def is_known_material(material_id: str) -> bool:
    return material_id in MATERIAL_CATALOG


def material_dtype(material_id: str) -> MaterialDType | None:
    """材料idのdtype（`MaterialDType`）。未知の材料idにはNoneを返す
    （呼び出し側は`is_known_material`で存在確認済みの前提だが、念のため例外にはしない）。"""
    spec = MATERIAL_CATALOG.get(material_id)
    return spec.dtype if spec is not None else None


MaterialArrayGroup = Literal["numeric", "boolean", "categorical"]


def material_array_group(spec: MaterialSpec) -> MaterialArrayGroup:
    """その材料の値をどのdtypeの行列へ載せるか。

    真偽の材料でも`bool_default="nan"`のもの（「不明」を「非該当」と混同してはいけない
    材料）はNaNを持てる必要があるため数値側へ載る。この判定はここだけが持つ——
    載せる側と読む側がそれぞれ判定すると、食い違ったとき列が静かに別の行列へ行く。
    """
    if spec.dtype == "categorical":
        return "categorical"
    if spec.dtype == "boolean" and spec.bool_default == "false":
        return "boolean"
    return "numeric"


def material_array_columns() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """dtypeの群ごとの材料idと、その並び（数値・真偽・分類）。

    行列の列がどう並ぶかの唯一の定義。組み立てる側と読む側が別々に並べると、
    材料を1つ足したときに列の意味が静かにずれる。
    """
    groups: dict[str, list[str]] = {"numeric": [], "boolean": [], "categorical": []}
    for material_id in sorted(material_value_sql()):
        groups[material_array_group(MATERIAL_CATALOG[material_id])].append(material_id)
    return tuple(groups["numeric"]), tuple(groups["boolean"]), tuple(groups["categorical"])


def material_value_sql() -> dict[str, str]:
    """材料id→値を求めるSQL式。カタログから導く（別の辞書を持たない）。"""
    return {
        material_id: spec.value_sql
        for material_id, spec in MATERIAL_CATALOG.items()
        if spec.value_sql is not None
    }


def material_coverage_specs() -> dict[str, WayMaterialCoverageSpec | EdgeMaterialCoverageSpec]:
    """欠損率を測る材料id→測り方。カタログから導く（別の辞書を持たない）。"""
    return {
        material_id: spec.coverage
        for material_id, spec in MATERIAL_CATALOG.items()
        if not isinstance(spec.coverage, CoverageExcluded)
    }


def material_coverage_exclusions() -> dict[str, str]:
    """欠損率を測らない材料id→その理由。"""
    return {
        material_id: spec.coverage.reason
        for material_id, spec in MATERIAL_CATALOG.items()
        if isinstance(spec.coverage, CoverageExcluded)
    }
