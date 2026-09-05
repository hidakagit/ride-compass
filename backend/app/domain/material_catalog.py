"""評価軸が参照する材料（material）の正式カタログ（改善計画T277）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`の各軸（`MaterialTerm.material`・
`CategoricalShape.material`）が参照する材料idは、これまで
`AXIS_DEFINITIONS`のコメントに散文で説明されるだけで、正式な一覧として宣言されていな
かった（軸スタジオ実装時、フロント側`axisMaterialsCatalog.ts`が独自にハードコードして
いた）。本モジュールがその単一ソースになる。

**材料の「登録」と「評価軸での利用」は独立している（改善計画T290）**: MVTタイル
（`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`）には、既存8軸が実際に使う
材料以外にも多くの生データ（highway・surface・smoothness等）が
既に焼き込まれている。設計の一貫性のため、これらも「評価や地図描画に使えそうな
生データ」として本カタログへ網羅的に登録する（ユーザー方針、2026-08-24）。
`dtype="categorical"`の材料は、改善計画T292で`domain/axis_definitions.py: CategoricalShape`
（`mapping: dict[bool | str, float]`）が文字列多値も扱えるよう拡張されたため、既に
car_stress軸の内部軸（highway、car_stress_highway_base）が実際に利用している
（改善計画T347: 自転車インフラの内部軸`car_stress_bicycle_infra_adjustment`は
7値categorical材料`bicycle_infra`ではなく正規化フラグ材料4件のbreakpoint_linear合成へ
既にT336で移行済みだったため、`bicycle_infra`材料自体は評価軸未使用のまま残置されていたが、
T347で削除した）。それ以外のcategorical材料は
登録済みでも対応する軸が無ければ評価には使われない（軸スタジオの材料選択肢には現れる）。

**設計方針（ユーザー指示、2026-08-24）**: 材料は今後システムメンテナンス（コード変更＋
デプロイ）によって増減されうるものとして設計するが、材料自体をGUIから追加・編集・削除
できるようにはしない。軸スタジオ（`/admin`）が材料を選ぶ際は、本カタログを
`GET /api/material-catalog`経由で動的に取得する（`api/routers/material_catalog.py`）。
新しい材料を増やすときはこのファイルへ1件追加するだけで、フロントのコード変更・
再デプロイなしに軸コンポーザーの選択肢へ現れる。

`tile_property`はMVTタイル（`road_graph_repository.py:
_ROAD_SURFACE_TILE_MVT_SQL`）に既に焼き込まれているプロパティ名（無ければ材料が
タイル非依存＝地図レイヤーのramp自動生成が不可能なことを表す）。`GET /api/material-catalog`
の公開レスポンスには含めない（フロントの軸コンポーザーが必要とするのは`material_id`/
`label`/`dtype`のみで、tileの内部実装詳細を露出させる理由が無いため）——地図表示ルール
自動生成（`domain/axis_display.py: derive_ramp_inputs`）がbackend内部でのみこの
フィールドを使う。
"""

from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict

from app.domain.attributes import ElevationAttribute
from app.domain.designation import CAR_STRESS_DESIGNATION_KINDS
from app.domain.graph import EdgeLike
from app.domain.recipe import bicycle_infra_flags_or_none, parse_lanes, parse_maxspeed, tag_value_is
from app.domain.road import classify_osm_surface

MaterialDType = Literal["numeric", "boolean", "categorical"]


@dataclass(frozen=True)
class MaterialExtractionContext:
    """改善計画T280: `domain/evaluation.py: compute_edge_costs_bulk`の抽出フェーズが
    Edge単位に組み立てる入力の束。`MaterialSpec.extractor`はこれを受け取り、その材料の
    Edge1件分の生値（欠損はNone）を返す。way_tags以外のフィールドはcompute_edge_costs_bulk
    側で`None`から`{}`/`set()`へ正規化済みの前提（呼び出し元でNoneチェック不要）。"""

    edge: EdgeLike
    edge_id: str
    way_tags: dict[str, str] | None
    distance_km: float
    elevation_attributes: dict[str, ElevationAttribute]
    surface_attributes: dict[str, str | None]
    stop_counts: dict[str, int]
    intersection_counts: dict[str, int]
    accident_counts: dict[str, int]
    accident_years_covered: int
    designated_edge_ids: set[str]


MaterialExtractor = Callable[[MaterialExtractionContext], object]


class MaterialSpec(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    material_id: str
    label: str
    # 改善計画T345: 軸スタジオの材料選択で、labelだけでは何を表す材料か分かりにくいという
    # ユーザーフィードバックへの対応。GET /api/material-catalogの公開レスポンスへ含め、
    # フロント側は選択中の材料の隣に情報アイコン(ⓘ)でこの説明文を表示する（AxisComposer.tsx:
    # MaterialInfoButton）。extractor未配線（DEFER）の材料は、選んでも評価軸としては
    # 機能しない旨をここに明記する（配線状況が変わったら追従が必要）。
    description: str
    dtype: MaterialDType
    # 値の単位（凡例・数値表示用の表記、無次元・真偽値・カテゴリ値は空文字）。地図の凡例が
    # 材料の生値を表示するときの単位の唯一の正（frontendは単位を持たない）。
    unit: str = ""
    # MVTタイルへ既に焼き込み済みのプロパティ名。Noneは「タイル非依存」（GSI標高の都度取得、
    # 気象の動的取得、レシピ合成値等）で、地図レイヤーのramp自動生成対象になりえない。
    tile_property: str | None = None
    # 改善計画T278: tile_propertyの生値と材料の値がスケール不一致（実行時に変動する係数での
    # 変換が必要）な場合True。例: accident_count_per_km_yearは収録年数（実行時にDBから
    # 取得、増え続ける）で正規化済みだが、tile_propertyのaccident_per_kmは年正規化前の生値。
    # domain/axis_display.py: derive_ramp_inputsはこれがTrueの材料を含む軸のramp自動導出を
    # 拒否する（静的な変換係数を持てないため、閾値を安全に流用できない）。
    tile_property_needs_runtime_scale: bool = False
    # 改善計画T308: 材料の値が進行方向によって変わる（有向）場合True。地図のrampレイヤーは
    # 1本の線を単色で塗る前提のため、方向依存材料は単純な重み付き和で表現できない
    # （時間依存の風レイヤー・降水ナウキャストと同じく、矢印等の専用表示が別途必要）。
    # derive_ramp_inputsはこれがTrueの材料を含む軸のramp自動導出を拒否する。現行
    # MATERIAL_CATALOGに該当する材料は無い（onewayはどの軸の材料にもなっていない表示専用の
    # 一次属性、T289）が、将来方向依存材料が追加された際に安全側へ倒す型的な安全弁として
    # 用意する。
    tile_property_direction_dependent: bool = False
    # 改善計画T404: この材料がdtype="boolean"だが、タイル側には対応する真偽値プロパティが
    # 無く、代わりに複数値の文字列(categorical)プロパティ`tile_property`の値がここに列挙する
    # 「いずれか」に該当する場合にtrueとみなせる場合に設定する（例: is_designated——
    # 評価時はdesignated_edge_idsから都度算出するタイル非依存の材料だが、地図表示の
    # 自動導出（derive_ramp_inputs、axis_display.py）向けには、同じ情報を持つ既存の
    # タイルプロパティ"designation"[3値categorical、emergency_transport/critical_logistics/
    # both]を「trueに該当するどれか」として流用できる）。設定する場合は`tile_property`も
    # 必ずそのcategoricalプロパティ名にすること。derive_ramp_inputsはこの材料が
    # CategoricalShapeのbool2値mappingに使われた場合、`categories={v: true_score for v in
    # tile_property_categorical_true_values}`というTileInputSpecへ変換する（categories
    # 未該当は常に寄与0扱いのため、false_score=0.0の場合のみ安全に表現できる。それ以外は
    # 安全側でNoneを返し自動導出を諦める）。
    tile_property_categorical_true_values: tuple[str, ...] | None = None
    # 改善計画T308: この材料の由来となる一次属性id（domain/registry.py:
    # PrimaryAttributeSpec.attr_id、frontend側はprimaryAttributes.ts:
    # PRIMARY_ATTRIBUTE_LAYER_IDS/PRIMARY_ATTRIBUTE_CHIP_LABELSのキー）。材料id（例:
    # bicycle_infra・maxspeed_kmh・stop_count_per_km）と一次属性id（例: cycleway・
    # maxspeed・stop_poi）は名前が異なる別の名前空間のため、対応が自明でない材料には
    # 明示的にここへ書く。Noneは「対応する一次属性が無い」（動的データ由来のwind_drag_ratio、
    # 一次属性未登録のbridge/smoothness等）。GET /api/axis-catalogが軸ごとにこれを解決して
    # 返すことで、frontend側（axisMaterialLayerIds、MapOverlayControls.tsxの材料一覧表示）が
    # 軸スタジオ作成軸に対しても同じ仕組みで動く（従来はビルド時静的生成物
    # axis-catalog.jsonのregistry.py: AxisSpec.inputs[一次属性id]をそのまま使っており、
    # GUI作成軸を含まなかった）。
    primary_attribute_id: str | None = None
    # 改善計画T280: この材料をcompute_edge_costs_bulkの抽出フェーズへ載せる関数
    # （MaterialExtractionContext -> 生値、欠損はNone）。Noneは「専用の計算経路を持つため
    # 汎用抽出の対象外」（風の材料: `evaluation.py: DYNAMIC_MATERIAL_EVALUATORS`がリクエスト
    # 時にbearing配列から完全ベクトル化で計算し、Edge単位のPythonループを経由しない。
    # designation: 種別ごとのper-edge kindが評価パイプラインへ配線されていない、
    # is_designatedのdocstring参照）。GET /api/material-catalogの公開レスポンスには
    # 含めない（tile_propertyと同じくbackend内部専用）。
    extractor: MaterialExtractor | None = None
    # dtype="boolean"の材料でextractorがNoneを返した（＝欠損）ときの配列上の扱い。
    # "false": bool配列、欠損はFalse（「タグ不在=非該当」とみなす多数派、motor_vehicle_no等）。
    # "nan": float配列、欠損はNaN（「不明を非該当と混同しない」判断がある少数派、
    # surface_good）。domain/axis_definitions.py: evaluate_axis_arrayの
    # `values.dtype == bool`分岐（priority_overridesの真偽比較）が実際に配列dtypeを
    # 見て分岐するため、この2表現は数値的に等価ではなく、材料ごとに固定する必要がある
    # （改善計画T280で発見、統一すると当該分岐が壊れる）。
    bool_default: Literal["false", "nan"] = "false"
    # 改善計画T338: この材料を軸スタジオ（`GET /api/material-catalog`の公開レスポンス）
    # から除外し、地図表示（tile_property・primary_attribute_id経由の凡例等）専用に
    # 限定する場合True。「登録されているが評価軸から未参照」な材料は他にも複数ある
    # （bridge/oneway/smoothness等）が、これらは単に軸がまだ無いだけで正規化フラグ・
    # 線形結合による評価軸化に技術的な障害は無い。designationはそれらと異なり、
    # 3値中"both"が実データで35.01%という高頻度で発生する構造的AND条件
    # （decisions/material-normalization-for-axis-composition.md参照）を持ち、
    # CategoricalShapeで素朴に値ごとスコアを付けても「AND条件」という実態を正しく
    # 表現できない（線形結合による近似も不向きと検証済み）。ユーザーが軸スタジオで
    # 誤って使い、意図と異なる評価軸を作ってしまうことを防ぐため、選択肢自体から
    # 除外する（評価目的で指定路線を使いたい場合は既に単純化済みの`is_designated`
    # [真偽値]を使う）。地図表示（`car_stress`の自動導出ramp表示[`derive_ramp_inputs`]・
    # `staticAttributeLayers.ts`の凡例）は本フラグと無関係にtile_property経由で
    # 引き続き動作する。
    display_only: bool = False
    # 改善計画T345フォローアップ: 材料の値（OSMタグ生値）ごとの日本語ラベル対訳表
    # （タグ値→ラベル）。highway/surface/smoothnessのようなオープンエンドな多値材料
    # だけが持つ（他は空dict）。軸スタジオ（AxisComposer.tsx）の「値の候補」セレクトが
    # `GET /api/material-catalog/{material_id}/values`経由で表示するラベルの単一ソース。
    # T340時点ではこの対訳表をfrontend側（地図の絞り込みUIのグルーピングを流用）に
    # 置いていたが、地図表示用のグルーピングは意図的に多対一（例: motorway/trunk/primary
    # 等複数値が同じ「幹線道路」）なため、候補セレクトへ流用すると同じラベルの選択肢が
    # 並び見分けが付かなくなる実害が判明した（ユーザー指摘「地図表示と評価は別」）。
    # 値の意味は材料そのものの定義に属するドメイン知識のため、他のフィールドと同じく
    # ここ（MaterialSpec自体）へ一元化する（material_id文字列をキーにした別の並列辞書に
    # すると、材料の追加・削除のたびに2箇所を同期する必要が生じ、過去に繰り返し実害を
    # 出してきた同期漏れパターン[T180・T185・T218のOpenAPIドリフト、T70・T93のタイル
    # 世代対上げ漏れ等]と同型のリスクを持ち込むため避ける）。
    value_labels: dict[str, str] = {}

    def value_label(self, value: str) -> str:
        """タグ生値から「論理名 - 物理名」形式の表示用ラベルを組み立てる（例:
        "自転車専用道 - cycleway"、改善計画T345さらなるフォローアップ2）。対訳表に無い値は
        物理名のみ返す（フォールバック、新しいOSMタグ値がDBに現れてもAPIが失敗しない
        ようにするため。この場合論理名が無いため" - "を付けない）。"""
        label = self.value_labels.get(value)
        if label is None:
            return value
        return f"{label} - {value}"

    def full_label(self) -> str:
        """材料名を「論理名 - 物理名」形式の表示用ラベルにする（例: "道路種別 - highway"、
        value_labelと同じ理由で軸スタジオの材料選択肢に物理名[material_id]を併記する、
        改善計画T345さらなるフォローアップ2）。"""
        return f"{self.label} - {self.material_id}"


# --- 改善計画T280: 抽出関数（compute_edge_costs_bulkの旧手書き抽出ループを1材料1関数へ
# 分解したもの。ロジック自体は移動のみで再実装していない——既存の判定プリミティブ
# [tag_value_is/parse_maxspeed/parse_lanes/classify_osm_surface]をそのまま呼ぶ）。
# way_tags依存の材料は
# way_tags自体が無いEdge（この場合car_stress軸グループ全体を評価しない、旧実装からの
# 既存挙動）でNoneを返し、bool系はbool_defaultの規約でFalseへ、それ以外はNaN/Noneへ
# 落ちる。新しい材料を1件増やすときは、この関数を1つ書いてMATERIAL_CATALOGへ
# extractorとして登録するだけでよく、compute_edge_costs_bulk自体の変更は不要
# （改善計画T339: 汎用パターンに収まる材料はここに専用関数を書く必要すら無く、下記
# raw_way_tag_extractor等の汎用ファクトリへMATERIAL_CATALOG側で直接パラメータを渡すだけで
# よい。gradient_percent/surface_good/surface/accident_count_per_km_year/is_designated/
# highway/bicycle_infraのように、材料固有の計算経路を持つものだけが専用関数のまま残る）。
def _extract_gradient_percent(ctx: MaterialExtractionContext) -> float | None:
    attribute = ctx.elevation_attributes.get(ctx.edge_id)
    return attribute.average_grade if attribute is not None else None


def _extract_surface_good(ctx: MaterialExtractionContext) -> bool | None:
    return classify_osm_surface(ctx.surface_attributes.get(ctx.edge_id))


def _extract_surface(ctx: MaterialExtractionContext) -> str | None:
    return ctx.surface_attributes.get(ctx.edge_id)


def _per_km(count: int | None, distance_km: float) -> float | None:
    if count is None or distance_km <= 0:
        return None
    return count / distance_km


# --- 改善計画T339: 汎用extractorファクトリ。material_catalog.pyのextractorのうち大半が
# 「単一タグの生値取得」「タグ値の単純一致判定」「数値パース」「件数/距離の密度計算」という
# 少数の汎用パターンに分類できる（T339背景参照）ことを踏まえ、材料ごとに専用のPython関数を
# 書く代わりに、ここで定義した汎用ファクトリへパラメータを渡して`MaterialExtractor`を
# 組み立てる。新しい材料がこれらのパターンに収まる限り、MATERIAL_CATALOGへの1エントリ
# 追加（`extractor=xxx_extractor(...)`という宣言）だけで抽出可能になり、専用関数を書く
# 必要が無い（tracktype材料が実例、下記参照）。優先順位付き分類（bicycle_infra）のような
# 複雑な組み合わせロジックは引き続き専用関数のままでよい（この汎用化の対象外）。
def raw_way_tag_extractor(tag: str, *, normalize: bool = False) -> MaterialExtractor:
    """「単一タグの生値取得」パターン（smoothness/tracktype等）。normalize=Trueで
    lower/btrim相当の正規化（surface/smoothnessタグと同じ流儀）。"""

    def _extract(ctx: MaterialExtractionContext) -> str | None:
        if ctx.way_tags is None:
            return None
        raw = ctx.way_tags.get(tag)
        if raw is None:
            return None
        return raw.strip().lower() if normalize else raw

    return _extract


def tag_equals_extractor(tag: str, expected: str, *, negate: bool = False) -> MaterialExtractor:
    """「タグ値の単純一致判定」パターン（motor_vehicle_no/has_tunnel/bridge等）。
    `domain/recipe.py: tag_value_is`をMaterialExtractionContext向けに包む。
    negate=Trueで判定を反転する（「タグ不在・不一致を陽性とみなす」材料向け）。"""

    def _extract(ctx: MaterialExtractionContext) -> bool | None:
        if ctx.way_tags is None:
            return None
        matched = tag_value_is(ctx.way_tags, tag, expected)
        return (not matched) if negate else matched

    return _extract


def way_tag_parser_extractor(parser: Callable[[dict[str, str]], int | None]) -> MaterialExtractor:
    """「数値パース」パターン（maxspeed_kmh/lanes_count等）。parserは
    `domain/recipe.py: parse_maxspeed`/`parse_lanes`のようなway_tags dict→パース済み値の
    既存正規化関数をそのまま渡す。"""

    def _extract(ctx: MaterialExtractionContext) -> int | None:
        if ctx.way_tags is None:
            return None
        return parser(ctx.way_tags)

    return _extract


def count_per_km_extractor(
    counts_selector: Callable[[MaterialExtractionContext], dict[str, int]],
) -> MaterialExtractor:
    """「件数/距離の密度計算」パターン（stop_count_per_km/intersection_count_per_km等）。
    counts_selectorはctxから該当する件数辞書（stop_counts/intersection_counts等）を
    選び出す関数。"""

    def _extract(ctx: MaterialExtractionContext) -> float | None:
        return _per_km(counts_selector(ctx).get(ctx.edge_id), ctx.distance_km)

    return _extract


def _extract_accident_count_per_km_year(ctx: MaterialExtractionContext) -> float | None:
    if ctx.accident_years_covered <= 0:
        return None
    per_km = _per_km(ctx.accident_counts.get(ctx.edge_id), ctx.distance_km)
    return per_km / ctx.accident_years_covered if per_km is not None else None


def _extract_is_designated(ctx: MaterialExtractionContext) -> bool:
    return ctx.edge_id in ctx.designated_edge_ids


# way_tags依存の材料群: way_tags自体が欠損のときNoneを返す（車ストレス軸グループを
# まとめて評価しない旧来の意図的な仕様を維持するため、タグ個別の欠損とは区別する）。
def _extract_highway(ctx: MaterialExtractionContext) -> str | None:
    return ctx.edge.highway if ctx.way_tags is not None else None


# 改善計画T336: 旧bicycle_infra材料（優先順位付き分類、改善計画T347で削除済み）を評価軸から
# 切り離すための正規化フラグ材料群。domain/traffic.py: 旧classify_bicycle_infrastructureの
# 判定条件のうち、cycleway/highway由来の部分（優先順位: track/highway=cycleway ＞ lane ＞
# shared_busway等）をそのままOR条件の真偽値へ分解したもの（decisions/material-normalization-for-
# axis-composition.md参照）。bicycle由来の分岐（shared_pedestrian・prohibited、
# highway×bicycleのAND条件）は正規化フラグの線形結合では近似できないと実データ検証済み
# のため意図的に対象外（軸定義側の車ストレス補正では「roadway」扱いへ丸められる、
# 実データでのズレ0.0127%は許容）。抽出ロジック自体は`domain/recipe.py: bicycle_infra_flags`
# へ集約し（evaluation.pyの各スカラー評価経路が同じ材料を手組みするmaterials辞書へ
# `**bicycle_infra_flags(...)`で混ぜ込む、bicycle_infra材料と同じ構成）、ここでは
# bulk抽出フェーズ（MaterialExtractionContext）向けの薄いラッパのみ持つ。
def _extract_highway_is_cycleway(ctx: MaterialExtractionContext) -> bool | None:
    flags = bicycle_infra_flags_or_none(ctx.way_tags, ctx.edge.highway)
    return None if flags is None else flags["highway_is_cycleway"]


def _extract_cycleway_has_track(ctx: MaterialExtractionContext) -> bool | None:
    flags = bicycle_infra_flags_or_none(ctx.way_tags, ctx.edge.highway)
    return None if flags is None else flags["cycleway_has_track"]


def _extract_cycleway_has_lane(ctx: MaterialExtractionContext) -> bool | None:
    flags = bicycle_infra_flags_or_none(ctx.way_tags, ctx.edge.highway)
    return None if flags is None else flags["cycleway_has_lane"]


def _extract_cycleway_has_shared(ctx: MaterialExtractionContext) -> bool | None:
    flags = bicycle_infra_flags_or_none(ctx.way_tags, ctx.edge.highway)
    return None if flags is None else flags["cycleway_has_shared"]


# 改善計画T359: highway=cycleway系材料とは別のOSMタグパターン（highway=footway/pathかつ
# bicycle=yes/designated、河川敷サイクリングロード等の「自転車通行可の歩行者道」）を検知する
# 正規化フラグ材料。王子-荒川ルート検索の調査で、この種の共用道が評価対象から漏れていたと
# 発覚（domain/recipe.py: bicycle_infra_flagsのdocstring参照）。抽出ロジック自体は
# bicycle_infra_flagsへ集約し、ここではbulk抽出フェーズ向けの薄いラッパのみ持つ
# （上記4関数と同じ構成）。
def _extract_shared_pedestrian_path(ctx: MaterialExtractionContext) -> bool | None:
    flags = bicycle_infra_flags_or_none(ctx.way_tags, ctx.edge.highway)
    return None if flags is None else flags["shared_pedestrian_path"]


# 改善計画T345フォローアップ: 材料の値（OSMタグ生値）ごとの日本語ラベル対訳表。
# MaterialSpec.value_labelsのdocstring参照——「地図表示と評価は別」という方針に基づき、
# 地図の絞り込みUI（components/Map/roadFilterAxes.ts: HIGHWAY_GROUPS/SURFACE_GROUPS、
# 意図的に多対一）とは独立した1値1ラベルの専用対訳表。各値の日本語ラベルはOSM wiki
# （Key:highway/Key:surface）の一般的なタグ定義に基づく。定義位置をMaterialSpecの
# コンストラクタ呼び出し直下ではなくここへ分けているのは、22〜24件のdict literalを
# 個々のMaterialSpec(...)呼び出しへインラインで書くと材料定義ブロックの見通しが悪くなる
# ため（値自体はvalue_labels=...で各MaterialSpecへそのまま渡し、単一ソースはあくまで
# MaterialSpec側——このモジュール内に閉じた実装都合の分割であり、material_id文字列を
# キーにした材料をまたぐ別辞書ではない）。
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


# 現行7公開軸＋car_stressを支える内部軸6つが参照する材料（AXIS_DEFINITIONSのコメントと
# 1:1対応）＋改善計画T290で追加した生データ（MVTタイルに焼き込み済みだが評価軸には
# 未使用のものを含む。カタログ冒頭のT290注記参照）。改善計画T292でcar_stress_levelを
# 撤去・is_designatedを追加した（旧専用Pythonレシピの廃止に伴う入れ替え）。
MATERIAL_CATALOG: dict[str, MaterialSpec] = {
    "gradient_percent": MaterialSpec(
        material_id="gradient_percent",
        label="勾配%（符号付き）",
        description="国土地理院の標高データから算出した進行方向の勾配（%）。登り坂はプラス、下り坂はマイナスです。",
        dtype="numeric",
        unit="%",
        # 標高自体はDEMタイル（infrastructure/tile_cache.py、永続・TTL無し）・Edge単位の
        # 計算済み属性（elevation_attributesテーブル、precompute_elevation_attributes
        # バッチ＋リクエスト時の遅延書き込みの両経路で埋まる）とも既に永続化されている
        # （改善計画T10・T218a、2026-08-30のT399調査で確認・本コメントの旧記述を訂正）。
        # タイルへ焼き込めない本当の理由は別にある: この値は進行方向依存の符号付き値
        # （登り坂プラス・下り坂マイナス）で、1つのOSM Way（地図上の1本の線）に対し
        # 往復2方向ぶんの異なる値を持ちうるため、方向を持たない静的なMVTタイルの
        # プロパティ1個には焼き込めない（風向風速と同じ制約）。
        # **改善計画T423で解決**: 方向依存材料を地図表示へ乗せる仕組みは、風と同型の
        # Redis経由way_id→値配信（`services/gradient_way_service.py`、
        # `GET /api/region/dynamic-way-values/gradient/{z}/{x}/{y}`）として実装した。
        # `tile_property`は今後も設定しない方針を確定する（MVT焼き込み経路[kind="ramp"、
        # `axis_display.py: derive_ramp_inputs`]はそもそも方向非依存の材料しか安全に
        # 表現できないため、`tile_property_direction_dependent=True`と両輪でこの材料が
        # ramp化されないことを明示する）。
        tile_property=None,
        tile_property_direction_dependent=True,
        primary_attribute_id="elevation",
        extractor=_extract_gradient_percent,
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
    ),
    # 本番DBの公開軸がまだ参照している非推奨エイリアス（値は進行方向に平行な風成分m/s、
    # `domain/wind.py: headwind_component_ms`）。軸スタジオの選択肢からは除外し、公開軸の
    # 参照先が`wind_drag_ratio`へ切り替わった後に撤去する。
    "wind_penalty": MaterialSpec(
        material_id="wind_penalty",
        label="向かい風ペナルティ(m/s、正=向かい風)【非推奨】",
        description="【非推奨、風の追加負荷(倍率)へ移行中】出発時刻の気象予報とルートの進行方向から算出した向かい風の強さ（m/s）。走行速度を考慮しません。",
        dtype="numeric",
        unit="m/s",
        tile_property=None,
        tile_property_direction_dependent=True,
        display_only=True,
    ),
    "surface_good": MaterialSpec(
        material_id="surface_good",
        label="舗装良否",
        description="OSMの路面タグ(surface)から判定した舗装の良否。true=舗装良好、false=未舗装等。",
        dtype="boolean",
        tile_property="surface_good",
        primary_attribute_id="surface",
        extractor=_extract_surface_good,
        # 「路面タグ不明」を「路面が悪い」と混同しないための唯一の例外（他のboolean材料は
        # bool_default既定の"false"のまま）。
        bool_default="nan",
    ),
    "stop_count_per_km": MaterialSpec(
        material_id="stop_count_per_km",
        label="停止密度(回/km)",
        description="信号・一時停止・踏切など、進行を妨げる要因の1kmあたりの発生回数。",
        dtype="numeric",
        tile_property="stop_per_km",
        primary_attribute_id="stop_poi",
        extractor=count_per_km_extractor(lambda ctx: ctx.stop_counts),
    ),
    "intersection_count_per_km": MaterialSpec(
        material_id="intersection_count_per_km",
        label="交差点密度(回/km)",
        description="接続する道路が3本以上ある交差点の1kmあたりの発生回数。",
        dtype="numeric",
        tile_property="intersection_per_km",
        primary_attribute_id="intersection",
        extractor=count_per_km_extractor(lambda ctx: ctx.intersection_counts),
    ),
    "accident_count_per_km_year": MaterialSpec(
        material_id="accident_count_per_km_year",
        label="事故密度(件/(km・年))",
        description="警察庁の事故データに基づく、1kmあたり・1年あたりの人身事故件数。",
        dtype="numeric",
        # タイル側は年正規化前の"accident_per_km"（収録全年分の重み付き件数/km）。
        # 年正規化はAXIS_DEFINITIONS側の評価ロジックが行うため、ramp化する場合は
        # 閾値をタイル側のスケールへ再換算する必要がある。収録年数は実行時にDBから
        # 取得し増え続けるため、静的な変換係数を持てない（改善計画T278で判明、
        # registry_defaults.pyの既存accident表示は手書きのまま維持する）。
        tile_property="accident_per_km",
        tile_property_needs_runtime_scale=True,
        primary_attribute_id="accident_point",
        extractor=_extract_accident_count_per_km_year,
    ),
    "lit": MaterialSpec(
        material_id="lit",
        label="街灯あり",
        description="OSMの街灯タグ(lit=yes)に該当する区間はtrue。タグ不在はfalse（街灯なし扱い）。",
        dtype="boolean",
        tile_property="lit",
        primary_attribute_id="lit",
        extractor=tag_equals_extractor("lit", "yes"),
    ),
    "has_tunnel": MaterialSpec(
        material_id="has_tunnel",
        label="トンネル",
        description="OSMのトンネルタグ(tunnel=yes)に該当する区間はtrue。",
        dtype="boolean",
        tile_property="tunnel",
        primary_attribute_id="tunnel",
        extractor=tag_equals_extractor("tunnel", "yes"),
    ),
    # --- 改善計画T290: MVTタイルに焼き込み済みだが評価軸には未使用の生データ ---
    "bridge": MaterialSpec(
        material_id="bridge",
        label="橋・高架",
        description="OSMの橋・高架タグ(bridge=yes)に該当する区間はtrue。",
        dtype="boolean",
        # OSMのbridgeタグ（yesのみtrue、それ以外はキー省略＝unknown/false扱い）。
        tile_property="bridge",
        # bridgeに対応する一次属性は未登録（表示専用のtunnel/onewayと異なり一次属性
        # レジストリに追加されていない）。
        extractor=tag_equals_extractor("bridge", "yes"),
    ),
    "motor_vehicle_no": MaterialSpec(
        material_id="motor_vehicle_no",
        label="自動車通行不可",
        description="OSMのタグ(motor_vehicle=no)から判定した、自動車が通行できない区間かどうか。",
        dtype="boolean",
        # OSMのmotor_vehicleタグがnoの区間（car_stress_motor_vehicle_no_adjustment内部軸
        # [domain/axis_definitions.py]でも参照される材料だが、軸合成前の生の真偽値自体は
        # 独立して材料登録していなかった）。
        tile_property="motor_vehicle_no",
        primary_attribute_id="motor_vehicle_access",
        extractor=tag_equals_extractor("motor_vehicle", "no"),
    ),
    "oneway": MaterialSpec(
        material_id="oneway",
        label="一方通行",
        description="OSMのタグから判定した一方通行区間かどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用）。",
        dtype="boolean",
        # osm_raw_ways.direction（forward/backward/both）から算出（改善計画T289で
        # 一次属性・地図レイヤーとして先行追加済み、本材料登録はその生値の網羅登録）。
        # 改善計画T280: extractor未設定（データ源のdirectionはEdgeLikeが持たず、
        # build_road_graphがforward/backward Edge生成の可否判定に消費するのみで
        # 保持しない。抽出フェーズへ載せるにはEdgeLikeへのフィールド追加が要り、
        # 表示専用の一方通行材料のためだけにそこまでする理由が今は無い、DEFER）。
        tile_property="oneway",
        primary_attribute_id="oneway",
    ),
    "maxspeed_kmh": MaterialSpec(
        material_id="maxspeed_kmh",
        label="制限速度(km/h)",
        description="OSMの制限速度タグ(maxspeed)から解析した制限速度（km/h）。",
        dtype="numeric",
        tile_property="maxspeed_kmh",
        primary_attribute_id="maxspeed",
        extractor=way_tag_parser_extractor(parse_maxspeed),
    ),
    "lanes_count": MaterialSpec(
        material_id="lanes_count",
        label="車線数",
        description="OSMの車線数タグ(lanes)から解析した車線数。",
        dtype="numeric",
        tile_property="lanes_count",
        primary_attribute_id="lanes",
        extractor=way_tag_parser_extractor(parse_lanes),
    ),
    "highway": MaterialSpec(
        material_id="highway",
        label="道路種別",
        description="OSMの道路種別タグ(highway)の生値（例: residential/primary/cycleway等）。値ごとに個別のスコアを設定できます。",
        dtype="categorical",
        # OSMのhighwayタグ生値（motorway/trunk/primary/secondary/tertiary/residential/
        # living_street/unclassified/track/cycleway/path/footway等）。取込プロファイル
        # （import_pbf.py: ALLOWED_HIGHWAY_TYPES）で許可された値のみ実際に現れる。
        # 正準の閉じた値集合はこのプロジェクトで管理していない（OSMタグの生値のため）。
        tile_property="highway",
        primary_attribute_id="highway",
        extractor=_extract_highway,
        value_labels=_HIGHWAY_VALUE_LABELS,
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
        extractor=_extract_surface,
        value_labels=_SURFACE_VALUE_LABELS,
    ),
    # 改善計画T347: 優先順位付き分類材料bicycle_infra（旧classify_bicycle_infrastructure
    # 由来）は、生データの分類・加工ロジックをPython側に手書きしないという設計方針に
    # 反していた（分類がSQL CASE式とPython関数の2箇所に独立して手書き複製されていた）
    # うえ、評価軸からも参照されなくなっていたため削除した。地図の専用レイヤー「自転車
    # インフラ」・car_stressランプのbicycle_infra項・classify_bicycle_infrastructure
    # 自体も同時に削除し、下の正規化フラグ材料4種の組み合わせのみを単一の情報源とする
    # （公開軸「自転車インフラ」[bicycle_infra_quality]がこれらを重み付き線形結合する、
    # domain/axis_definitions.py参照）。経緯はdocs/architecture.md「自転車インフラ」節・
    # docs/improvement-plan.md T347参照。
    # 改善計画T336: bicycle_infraを評価軸から切り離すための正規化フラグ材料群
    # （_extract_highway_is_cycleway等のdocstring参照）。
    # 改善計画T367（ユーザー要望「軸スタジオで作った推定軸を地図上アイコンで自動表示
    # したい」）: T347で旧bicycle_infraタイルプロパティを削除して以降tile_propertyを
    # 持たなかったため、公開軸「自転車インフラ」（bicycle_infra_quality）が
    # derive_ramp_inputs（domain/axis_display.py）の対象外＝地図に一切出ない状態が
    # 続いていた。5材料それぞれへ専用のtile_propertyを新設し、_ROAD_SURFACE_TILE_MVT_SQL
    # （road_graph_repository.py）へ焼き込む（is_emergency_transport/is_critical_logistics
    # [T338フォローアップ]と同じ「複雑な分類の生値は表示専用として残し、評価用の正規化
    # 材料は別途タイルへ焼き込む」設計）。
    "highway_is_cycleway": MaterialSpec(
        material_id="highway_is_cycleway",
        label="道路種別が自転車道",
        description="道路種別(highway)自体が自転車道(cycleway)かどうか。",
        dtype="boolean",
        tile_property="highway_is_cycleway",
        # 改善計画T347（ユーザー指摘: 実在しない疑似属性を発明する対症療法ではなく、
        # 実在の一次属性のうち片方だけへ寄せて解消する）。判定式はhighway生タグを見るが、
        # 意味的には他3材料と同じ「自転車走行環境の分類」という1つのまとまりのため、
        # cycleway_has_track等と同じprimary_attribute_id="cycleway"へ寄せる（highway自体は
        # car_stress_highway_baseが単独で使う一次属性のまま、排他チェック対象を維持する）。
        primary_attribute_id="cycleway",
        # 改善計画T347フォローアップ: bool_default既定の"false"のままだと、
        # compute_edge_costs_bulk（配列評価経路）が「データ欠損（extractorがNoneを返す）」を
        # 「確定でFalse」へ丸めてしまい、公開軸bicycle_infra_quality（改善計画T353で
        # car_stress_bicycle_infra_adjustment内部軸を廃止し直接この4材料を持つように
        # なった）がhighway未解決の区間を「roadway確定」と誤評価する
        # （surface_goodと同じ「不明をFalseと混同してはいけない」ケース）。4材料は常に
        # bicycle_infra_flagsから一括で算出される（個別に欠損することはない）ため、
        # 4件まとめて"nan"にしても副作用は無い。
        bool_default="nan",
        extractor=_extract_highway_is_cycleway,
    ),
    "cycleway_has_track": MaterialSpec(
        material_id="cycleway_has_track",
        label="自転車道(track)を併設",
        description="車道と分離された自転車道(cycleway=track)を併設しているかどうか。",
        dtype="boolean",
        tile_property="cycleway_has_track",
        primary_attribute_id="cycleway",
        bool_default="nan",
        extractor=_extract_cycleway_has_track,
    ),
    "cycleway_has_lane": MaterialSpec(
        material_id="cycleway_has_lane",
        label="自転車レーン(lane)を併設",
        description="車道上に線で区切られた自転車レーン(cycleway=lane)を併設しているかどうか。",
        dtype="boolean",
        tile_property="cycleway_has_lane",
        primary_attribute_id="cycleway",
        bool_default="nan",
        extractor=_extract_cycleway_has_lane,
    ),
    "cycleway_has_shared": MaterialSpec(
        material_id="cycleway_has_shared",
        label="バス共用等の自転車レーンを併設",
        description="バス専用レーン共用など、簡易な自転車レーン(cycleway=shared_busway/shared_lane)を併設しているかどうか。",
        dtype="boolean",
        tile_property="cycleway_has_shared",
        bool_default="nan",
        primary_attribute_id="cycleway",
        extractor=_extract_cycleway_has_shared,
    ),
    "shared_pedestrian_path": MaterialSpec(
        material_id="shared_pedestrian_path",
        label="歩行者自転車共用道",
        description="車道と分離された歩行者道のうち、自転車の通行が認められている区間（河川敷サイクリングロード等、highway=footway/pathかつbicycle=yes/designated）かどうか。",
        dtype="boolean",
        tile_property="shared_pedestrian_path",
        primary_attribute_id="cycleway",
        bool_default="nan",
        extractor=_extract_shared_pedestrian_path,
    ),
    "designation": MaterialSpec(
        material_id="designation",
        label="指定路線",
        description="指定路線の種別（緊急輸送道路[N10]・重要物流道路[N12]・両方該当）。3値の複合判定のため評価軸では使えません（地図表示専用）。評価で使う場合は緊急輸送道路該当[N10]・重要物流道路該当[N12]・指定路線該当のいずれかを使ってください。",
        dtype="categorical",
        # 国土数値情報N10/N12該当区分（emergency_transport/critical_logistics/both、
        # 外部静的データソースT51）。未該当はタイル側でプロパティ省略。
        # 改善計画T280: extractor未設定（種別ごとのper-edge kindがcompute_edge_costs_bulkへ
        # 配線されていない。is_designatedのコメントにある既存DEFERとまとめて扱う）。
        tile_property="designation",
        primary_attribute_id="designation",
        # 改善計画T338: display_onlyのdocstring参照（"both"のAND条件が実データで35.01%と
        # 構造的に頻発するため、軸スタジオでの評価軸材料としての選択肢からは除外する）。
        # 地図表示（staticAttributeLayers.tsの凡例、車ストレス表示の自動導出ramp表示等）は
        # 引き続きこの3値プロパティを使う（ユーザー判断、2026-08-26）。評価軸で種別を
        # 区別したい場合はis_emergency_transport/is_critical_logistics（下記）を使う。
        display_only=True,
    ),
    "is_emergency_transport": MaterialSpec(
        material_id="is_emergency_transport",
        label="緊急輸送道路該当[N10]（真偽）",
        description="緊急輸送道路[N10]に指定されているかどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用。評価で使う場合は指定路線該当を使ってください）。",
        dtype="boolean",
        # 改善計画T338フォローアップ（2026-08-26、ユーザー指摘）: designation（3値、
        # 優先順位付き分類）をbicycle_infra（改善計画T336）と同じ設計思想で正規化する。
        # is_ert/is_clは_ROAD_SURFACE_TILE_MVT_SQLが既に計算していた中間値で、'both'/
        # 'emergency_transport'/'critical_logistics'へ畳み込む前の生フラグをそのまま
        # 2材料として個別に焼き込む。
        tile_property="is_emergency_transport",
        primary_attribute_id="designation",
        # extractor未設定（is_designatedと同じ「トリガー付きDEFER」、設計原則9）。
        # is_designated（下記）と異なりどの内蔵軸からも参照されない——ユーザー指示
        # 「特定路線かどうかだけで評価は判定」の通り、car_stress_designation_adjustment
        # 内部軸は今後もis_designatedのみを使う。本材料は軸スタジオでユーザーが種別を
        # 区別する評価軸を自作したくなった時点で初めて配線する（種別ごとのper-edge kindを
        # compute_edge_costs_bulk/3つのスカラー評価経路へ運ぶ配線は、実際にそのニーズが
        # 出るまで新設しない）。
        extractor=None,
    ),
    "is_critical_logistics": MaterialSpec(
        material_id="is_critical_logistics",
        label="重要物流道路該当[N12]（真偽）",
        description="重要物流道路[N12]に指定されているかどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用。評価で使う場合は指定路線該当を使ってください）。",
        dtype="boolean",
        # is_emergency_transportと対をなす材料。コメントは同上参照。
        tile_property="is_critical_logistics",
        primary_attribute_id="designation",
        extractor=None,
    ),
    "is_designated": MaterialSpec(
        material_id="is_designated",
        label="指定路線該当（真偽）",
        description="緊急輸送道路・重要物流道路のいずれかに指定されているかどうか（種別は区別しません）。",
        dtype="boolean",
        # 改善計画T292: car_stress軸の内部軸（designation由来の調整軸）が使う簡略化された
        # 真偽値材料。指定路線の種別（emergency_transport/critical_logistics/both、材料
        # "designation"、改善計画T338フォローアップで正規化フラグ版のis_emergency_transport/
        # is_critical_logisticsも追加）は評価パイプライン側で種別ごとに区別して保持していない
        # （domain/designation.py: 補正量が種別によらず一律+1のため、種別を評価まで
        # 運ぶ配線を新設する理由が無い）。評価時（extractor）はcar_stress_designation_
        # adjustment内部軸と同じくタイル非依存（designated_edge_idsから都度算出）のまま
        # 変更しない。
        #
        # 改善計画T404: 一方、地図表示の自動導出（derive_ramp_inputs、axis_display.py）向けに
        # `tile_property`は"designation"（3値categorical、既に他の材料"designation"が使う
        # 同じタイルプロパティ）を指す。指定路線該当=このプロパティが既知の3値
        # （emergency_transport/critical_logistics/both、_ROAD_SURFACE_TILE_MVT_SQL
        # [road_graph_repository.py]のCASE式が書き込む値と1:1）のいずれかであることと
        # 同値なため、`tile_property_categorical_true_values`で表現する。評価用の
        # extractorはdesignated_edge_ids由来のまま変えないため、この2つの経路
        # （評価/地図表示）が別ソースを見ている点はis_designated材料に限った既知の
        # 非対称——値そのものは常に一致する（両方ともKSJ N10/N12マッチング結果由来）ため
        # 実害はない。
        tile_property="designation",
        tile_property_categorical_true_values=(*sorted(CAR_STRESS_DESIGNATION_KINDS), "both"),
        primary_attribute_id="designation",
        extractor=_extract_is_designated,
    ),
    "smoothness": MaterialSpec(
        material_id="smoothness",
        label="路面の状態",
        description="OSMの路面状態タグ(smoothness)の生値（excellent〜impassableの7段階）。同じ路面種別(surface)でも実際の荒れ具合を区別したい場合に使います。",
        dtype="categorical",
        # OSMのsmoothnessタグ生値（excellent/good/intermediate/bad/very_bad/horrible/
        # very_horrible/impassable、正規化: lower/btrim）。surfaceが路面「種別」なのに
        # 対し、smoothnessは実際の走行感（同じasphaltでも荒れ具合が違う等）。
        tile_property="smoothness",
        # smoothnessに対応する一次属性は未登録（bridgeと同じくレジストリ未追加）。
        extractor=raw_way_tag_extractor("smoothness", normalize=True),
        value_labels=_SMOOTHNESS_VALUE_LABELS,
    ),
    # 改善計画T339完了条件の実証: 専用のPython関数を書かず、汎用ファクトリ
    # （raw_way_tag_extractor）への宣言追加だけで抽出可能にした新規材料。tracktypeは
    # OSMの未舗装路面グレード（grade1[良好]〜grade5[粗悪]）で、smoothnessと同じ
    # 「単一タグの生値取得（正規化: lower/btrim）」パターンにそのまま収まる。
    # MVTタイルへは未焼き込み（新規追加のため、他の材料と異なりT290の「既存焼き込み済み
    # データの網羅登録」ではない。地図表示で必要になれば別途タイルへ追加する）。
    "tracktype": MaterialSpec(
        material_id="tracktype",
        label="未舗装路グレード(tracktype)",
        description="OSMの未舗装路グレードタグ(tracktype)の生値（grade1[良好]〜grade5[粗悪]）。",
        dtype="categorical",
        tile_property=None,
        extractor=raw_way_tag_extractor("tracktype", normalize=True),
    ),
}


def axis_studio_materials() -> list[MaterialSpec]:
    """改善計画T338: 軸スタジオの材料選択肢（`GET /api/material-catalog`公開レスポンス）
    向けに`display_only`材料を除外した一覧。`display_only`は選択肢からの除外のみを
    意味し、材料idとしての正当性（`is_known_material`）には影響しない
    （designationのdocstring参照）。"""
    return [spec for spec in MATERIAL_CATALOG.values() if not spec.display_only]


def is_known_material(material_id: str) -> bool:
    return material_id in MATERIAL_CATALOG


def material_dtype(material_id: str) -> MaterialDType | None:
    """材料idのdtype（numeric/boolean）。未知の材料idにはNoneを返す
    （呼び出し側は`is_known_material`で存在確認済みの前提だが、念のため例外にはしない）。"""
    spec = MATERIAL_CATALOG.get(material_id)
    return spec.dtype if spec is not None else None
