"""評価軸が参照する材料（material）の正式カタログ（改善計画T277）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`の各軸（`MaterialTerm.material`・
`CategoricalShape.material`・`FlagSumShape.flags`）が参照する材料idは、これまで
`AXIS_DEFINITIONS`のコメントに散文で説明されるだけで、正式な一覧として宣言されていな
かった（軸スタジオ実装時、フロント側`axisMaterialsCatalog.ts`が独自にハードコードして
いた）。本モジュールがその単一ソースになる。

**材料の「登録」と「評価軸での利用」は独立している（改善計画T290）**: MVTタイル
（`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`）には、既存7軸が実際に使う
材料以外にも多くの生データ（highway・surface・smoothness・bicycle_infra等）が
既に焼き込まれている。設計の一貫性のため、これらも「評価や地図描画に使えそうな
生データ」として本カタログへ網羅的に登録する（ユーザー方針、2026-08-24）。
`dtype="categorical"`の材料は、改善計画T292で`domain/axis_definitions.py: CategoricalShape`
（`mapping: dict[bool | str, float]`）が文字列多値も扱えるよう拡張されたため、既に
car_stress軸の内部軸（highway・bicycle_infra、car_stress_highway_base/
car_stress_bicycle_infra_adjustment）が実際に利用している。それ以外のcategorical材料は
登録済みでも対応する軸が無ければ評価には使われない（軸スタジオの材料選択肢には現れる）。

**設計方針（ユーザー指示、2026-08-24）**: 材料は今後システムメンテナンス（コード変更＋
デプロイ）によって増減されうるものとして設計するが、材料自体をGUIから追加・編集・削除
できるようにはしない。軸スタジオ（`/admin`）が材料を選ぶ際は、本カタログを
`GET /api/material-catalog`経由で動的に取得する（`api/routers/material_catalog.py`）。
新しい材料を増やすときはこのファイルへ1件追加するだけで、フロントのコード変更・
再デプロイなしに軸コンポーザーの選択肢へ現れる。

`tile_property`/`tile_property_inverted`はMVTタイル（`road_graph_repository.py:
_ROAD_SURFACE_TILE_MVT_SQL`）に既に焼き込まれているプロパティ名（無ければ材料が
タイル非依存＝地図レイヤーのramp自動生成が不可能なことを表す）。`GET /api/material-catalog`
の公開レスポンスには含めない（フロントの軸コンポーザーが必要とするのは`material_id`/
`label`/`dtype`のみで、tileの内部実装詳細を露出させる理由が無いため）——地図表示ルール
自動生成タスク（T278、未起票）がbackend内部でのみこの2フィールドを使う想定。
"""

from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict

from app.domain.attributes import ElevationAttribute
from app.domain.graph import EdgeLike
from app.domain.recipe import bicycle_infra_flags
from app.domain.recipe import cycleway_class as _cycleway_class
from app.domain.recipe import parse_lanes, parse_maxspeed, tag_value_is
from app.domain.road import classify_osm_surface
from app.domain.traffic import classify_bicycle_infrastructure

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
    dtype: MaterialDType
    # MVTタイルへ既に焼き込み済みのプロパティ名。Noneは「タイル非依存」（GSI標高の都度取得、
    # 気象の動的取得、レシピ合成値等）で、地図レイヤーのramp自動生成対象になりえない。
    tile_property: str | None = None
    # tile_propertyの符号反転が必要か（例: no_lit材料はタイルのlitプロパティの否定）。
    tile_property_inverted: bool = False
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
    # 改善計画T308: この材料の由来となる一次属性id（domain/registry.py:
    # PrimaryAttributeSpec.attr_id、frontend側はprimaryAttributes.ts:
    # PRIMARY_ATTRIBUTE_LAYER_IDS/PRIMARY_ATTRIBUTE_CHIP_LABELSのキー）。材料id（例:
    # bicycle_infra・maxspeed_kmh・stop_count_per_km）と一次属性id（例: cycleway・
    # maxspeed・stop_poi）は名前が異なる別の名前空間のため、対応が自明でない材料には
    # 明示的にここへ書く。Noneは「対応する一次属性が無い」（動的データ由来のwind_penalty、
    # 一次属性未登録のbridge/smoothness等）。GET /api/axis-catalogが軸ごとにこれを解決して
    # 返すことで、frontend側（axisMaterialLayerIds、MapOverlayControls.tsxの材料一覧表示）が
    # 軸スタジオ作成軸に対しても同じ仕組みで動く（従来はビルド時静的生成物
    # axis-catalog.jsonのregistry.py: AxisSpec.inputs[一次属性id]をそのまま使っており、
    # GUI作成軸を含まなかった）。
    primary_attribute_id: str | None = None
    # 改善計画T280: この材料をcompute_edge_costs_bulkの抽出フェーズへ載せる関数
    # （MaterialExtractionContext -> 生値、欠損はNone）。Noneは「専用の計算経路を持つため
    # 汎用抽出の対象外」（wind_penalty: 風向×bearingの完全ベクトル化済み計算で、そもそも
    # Edge単位のPythonループを経由しない。designation: 種別ごとのper-edge kindが評価
    # パイプラインへ配線されていない、is_designatedのdocstring参照）。GET /api/material-catalog
    # の公開レスポンスには含めない（tile_propertyと同じくbackend内部専用）。
    extractor: MaterialExtractor | None = None
    # dtype="boolean"の材料でextractorがNoneを返した（＝欠損）ときの配列上の扱い。
    # "false": bool配列、欠損はFalse（「タグ不在=非該当」とみなす多数派、motor_vehicle_no等）。
    # "nan": float配列、欠損はNaN（「不明を非該当と混同しない」判断がある少数派、
    # surface_good）。domain/axis_definitions.py: evaluate_axis_arrayの
    # `values.dtype == bool`分岐（priority_overridesの真偽比較）が実際に配列dtypeを
    # 見て分岐するため、この2表現は数値的に等価ではなく、材料ごとに固定する必要がある
    # （改善計画T280で発見、統一すると当該分岐が壊れる）。
    bool_default: Literal["false", "nan"] = "false"


# --- 改善計画T280: 抽出関数（compute_edge_costs_bulkの旧手書き抽出ループを1材料1関数へ
# 分解したもの。ロジック自体は移動のみで再実装していない——既存の判定プリミティブ
# [tag_value_is/parse_maxspeed/parse_lanes/classify_bicycle_infrastructure/
# classify_osm_surface/cycleway_class]をそのまま呼ぶ）。way_tags依存の材料は
# way_tags自体が無いEdge（この場合car_stress軸グループ全体を評価しない、旧実装からの
# 既存挙動）でNoneを返し、bool系はbool_defaultの規約でFalseへ、それ以外はNaN/Noneへ
# 落ちる。新しい材料を1件増やすときは、この関数を1つ書いてMATERIAL_CATALOGへ
# extractorとして登録するだけでよく、compute_edge_costs_bulk自体の変更は不要。
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


def _extract_stop_count_per_km(ctx: MaterialExtractionContext) -> float | None:
    return _per_km(ctx.stop_counts.get(ctx.edge_id), ctx.distance_km)


def _extract_intersection_count_per_km(ctx: MaterialExtractionContext) -> float | None:
    return _per_km(ctx.intersection_counts.get(ctx.edge_id), ctx.distance_km)


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


def _extract_bicycle_infra(ctx: MaterialExtractionContext) -> str | None:
    if ctx.way_tags is None:
        return None
    return classify_bicycle_infrastructure(ctx.way_tags, ctx.edge.highway)


def _extract_cycleway_class(ctx: MaterialExtractionContext) -> str | None:
    if ctx.way_tags is None:
        return None
    return _cycleway_class(ctx.way_tags)


# 改善計画T336: bicycle_infra材料（優先順位付き分類）を評価軸から切り離すための正規化
# フラグ材料群。domain/traffic.py: classify_bicycle_infrastructureの判定条件のうち、
# cycleway/highway由来の部分（優先順位: track/highway=cycleway ＞ lane ＞ shared_busway等）
# をそのままOR条件の真偽値へ分解したもの（decisions/material-normalization-for-
# axis-composition.md参照）。bicycle由来の分岐（shared_pedestrian・prohibited、
# highway×bicycleのAND条件）は正規化フラグの線形結合では近似できないと実データ検証済み
# のため意図的に対象外（軸定義側の車ストレス補正では「roadway」扱いへ丸められる、
# 実データでのズレ0.0127%は許容）。抽出ロジック自体は`domain/recipe.py: bicycle_infra_flags`
# へ集約し（evaluation.py/openrouteservice_engine.pyの3つのスカラー評価経路が同じ材料を
# 手組みするmaterials辞書へ`**bicycle_infra_flags(...)`で混ぜ込む、bicycle_infra材料と
# 同じ構成）、ここではbulk抽出フェーズ（MaterialExtractionContext）向けの薄いラッパのみ
# 持つ。
def _extract_highway_is_cycleway(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return bicycle_infra_flags(ctx.way_tags, ctx.edge.highway)["highway_is_cycleway"]


def _extract_cycleway_has_track(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return bicycle_infra_flags(ctx.way_tags, ctx.edge.highway)["cycleway_has_track"]


def _extract_cycleway_has_lane(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return bicycle_infra_flags(ctx.way_tags, ctx.edge.highway)["cycleway_has_lane"]


def _extract_cycleway_has_shared(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return bicycle_infra_flags(ctx.way_tags, ctx.edge.highway)["cycleway_has_shared"]


def _extract_maxspeed_kmh(ctx: MaterialExtractionContext) -> int | None:
    if ctx.way_tags is None:
        return None
    return parse_maxspeed(ctx.way_tags)


def _extract_lanes_count(ctx: MaterialExtractionContext) -> int | None:
    if ctx.way_tags is None:
        return None
    return parse_lanes(ctx.way_tags)


def _extract_motor_vehicle_no(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return tag_value_is(ctx.way_tags, "motor_vehicle", "no")


def _extract_no_lit(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return not tag_value_is(ctx.way_tags, "lit", "yes")


def _extract_has_tunnel(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return tag_value_is(ctx.way_tags, "tunnel", "yes")


def _extract_bridge(ctx: MaterialExtractionContext) -> bool | None:
    if ctx.way_tags is None:
        return None
    return tag_value_is(ctx.way_tags, "bridge", "yes")


def _extract_smoothness(ctx: MaterialExtractionContext) -> str | None:
    if ctx.way_tags is None:
        return None
    raw = ctx.way_tags.get("smoothness")
    return raw.strip().lower() if raw else None


# 現行7公開軸＋car_stressを支える内部軸6つが参照する材料（AXIS_DEFINITIONSのコメントと
# 1:1対応）＋改善計画T290で追加した生データ（MVTタイルに焼き込み済みだが評価軸には
# 未使用のものを含む。カタログ冒頭のT290注記参照）。改善計画T292でcar_stress_levelを
# 撤去・is_designatedを追加した（旧専用Pythonレシピの廃止に伴う入れ替え）。
MATERIAL_CATALOG: dict[str, MaterialSpec] = {
    "gradient_percent": MaterialSpec(
        material_id="gradient_percent",
        label="勾配%（符号付き）",
        dtype="numeric",
        # 標高は国土地理院APIから都度取得しDBへ恒久保存しない設計のため、タイルへ
        # 焼き込める事実データが無い（docs/architecture.md「標高計算」節参照）。
        tile_property=None,
        primary_attribute_id="elevation",
        extractor=_extract_gradient_percent,
    ),
    "wind_penalty": MaterialSpec(
        material_id="wind_penalty",
        label="向かい風ペナルティ(m/s、正=向かい風)",
        dtype="numeric",
        # 気象は動的データ（出発時刻依存）のためタイルに焼き込めない。対応する一次属性も
        # 未登録（動的気象は一次属性レジストリの対象外）。
        tile_property=None,
    ),
    "surface_good": MaterialSpec(
        material_id="surface_good",
        label="舗装良否",
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
        dtype="numeric",
        tile_property="stop_per_km",
        primary_attribute_id="stop_poi",
        extractor=_extract_stop_count_per_km,
    ),
    "intersection_count_per_km": MaterialSpec(
        material_id="intersection_count_per_km",
        label="交差点密度(回/km)",
        dtype="numeric",
        tile_property="intersection_per_km",
        primary_attribute_id="intersection",
        extractor=_extract_intersection_count_per_km,
    ),
    "accident_count_per_km_year": MaterialSpec(
        material_id="accident_count_per_km_year",
        label="事故密度(件/(km・年))",
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
    "no_lit": MaterialSpec(
        material_id="no_lit",
        label="街灯なし",
        dtype="boolean",
        # タイルのlitはタグ有無の真偽（yesのみtrue、それ以外はNULL）。no_lit材料は
        # その否定（litタグ不在は街灯なしとみなす安全側の判断、domain/night.py参照）。
        tile_property="lit",
        tile_property_inverted=True,
        primary_attribute_id="lit",
        extractor=_extract_no_lit,
    ),
    "has_tunnel": MaterialSpec(
        material_id="has_tunnel",
        label="トンネル",
        dtype="boolean",
        tile_property="tunnel",
        primary_attribute_id="tunnel",
        extractor=_extract_has_tunnel,
    ),
    # --- 改善計画T290: MVTタイルに焼き込み済みだが評価軸には未使用の生データ ---
    "bridge": MaterialSpec(
        material_id="bridge",
        label="橋・高架",
        dtype="boolean",
        # OSMのbridgeタグ（yesのみtrue、それ以外はキー省略＝unknown/false扱い）。
        tile_property="bridge",
        # bridgeに対応する一次属性は未登録（表示専用のtunnel/onewayと異なり一次属性
        # レジストリに追加されていない）。
        extractor=_extract_bridge,
    ),
    "motor_vehicle_no": MaterialSpec(
        material_id="motor_vehicle_no",
        label="自動車通行不可",
        dtype="boolean",
        # OSMのmotor_vehicleタグがnoの区間（car_stress_motor_vehicle_no_adjustment内部軸
        # [domain/axis_definitions.py]でも参照される材料だが、軸合成前の生の真偽値自体は
        # 独立して材料登録していなかった）。
        tile_property="motor_vehicle_no",
        primary_attribute_id="motor_vehicle_access",
        extractor=_extract_motor_vehicle_no,
    ),
    "oneway": MaterialSpec(
        material_id="oneway",
        label="一方通行",
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
        dtype="numeric",
        tile_property="maxspeed_kmh",
        primary_attribute_id="maxspeed",
        extractor=_extract_maxspeed_kmh,
    ),
    "lanes_count": MaterialSpec(
        material_id="lanes_count",
        label="車線数",
        dtype="numeric",
        tile_property="lanes_count",
        primary_attribute_id="lanes",
        extractor=_extract_lanes_count,
    ),
    "highway": MaterialSpec(
        material_id="highway",
        label="道路種別",
        dtype="categorical",
        # OSMのhighwayタグ生値（motorway/trunk/primary/secondary/tertiary/residential/
        # living_street/unclassified/track/cycleway/path/footway等）。取込プロファイル
        # （import_pbf.py: ALLOWED_HIGHWAY_TYPES）で許可された値のみ実際に現れる。
        # 正準の閉じた値集合はこのプロジェクトで管理していない（OSMタグの生値のため）。
        tile_property="highway",
        primary_attribute_id="highway",
        extractor=_extract_highway,
    ),
    "surface": MaterialSpec(
        material_id="surface",
        label="路面種別",
        dtype="categorical",
        # OSMのsurfaceタグ生値（正規化: lower/btrim）。良否の正準分類は
        # domain/road.py: GOOD_OSM_SURFACE_TAGS/BAD_OSM_SURFACE_TAGS参照（本材料は
        # その分類前の生タグ値そのもの。分類後の真偽値は既存材料surface_good）。
        tile_property="surface",
        primary_attribute_id="surface",
        extractor=_extract_surface,
    ),
    "bicycle_infra": MaterialSpec(
        material_id="bicycle_infra",
        label="自転車インフラ種別",
        dtype="categorical",
        # domain/traffic.py: classify_bicycle_infrastructureの分類値
        # （separated/lane/shared_busway/shared_pedestrian/prohibited/roadway。
        # unknownはタイル側でプロパティ省略として表現され現れない）。
        tile_property="bicycle_infra",
        primary_attribute_id="cycleway",
        extractor=_extract_bicycle_infra,
    ),
    # 改善計画T336: bicycle_infraを評価軸から切り離すための正規化フラグ材料群
    # （_extract_highway_is_cycleway等のdocstring参照）。地図表示用のtile_propertyは
    # 持たない（bicycle_infra/cycleway_classのタイルプロパティをそのまま流用でき、
    # 専用カラムを新設する理由が無い。wind_penalty/is_designatedと同じ評価パイプライン
    # 専用材料）。
    "highway_is_cycleway": MaterialSpec(
        material_id="highway_is_cycleway",
        label="道路種別が自転車道",
        dtype="boolean",
        tile_property=None,
        primary_attribute_id="highway",
        extractor=_extract_highway_is_cycleway,
    ),
    "cycleway_has_track": MaterialSpec(
        material_id="cycleway_has_track",
        label="自転車道(track)を併設",
        dtype="boolean",
        tile_property=None,
        primary_attribute_id="cycleway",
        extractor=_extract_cycleway_has_track,
    ),
    "cycleway_has_lane": MaterialSpec(
        material_id="cycleway_has_lane",
        label="自転車レーン(lane)を併設",
        dtype="boolean",
        tile_property=None,
        primary_attribute_id="cycleway",
        extractor=_extract_cycleway_has_lane,
    ),
    "cycleway_has_shared": MaterialSpec(
        material_id="cycleway_has_shared",
        label="バス共用等の自転車レーンを併設",
        dtype="boolean",
        tile_property=None,
        primary_attribute_id="cycleway",
        extractor=_extract_cycleway_has_shared,
    ),
    "cycleway_class": MaterialSpec(
        material_id="cycleway_class",
        label="自転車レーン種別",
        dtype="categorical",
        # 車ストレスのcycleway補正が参照する3値（track/lane/shared）。bicycle_infraより
        # 粗い分類（bicycle_infraのseparated/lane/shared_buswayに相当する部分集合）。
        tile_property="cycleway_class",
        primary_attribute_id="cycleway",
        extractor=_extract_cycleway_class,
    ),
    "designation": MaterialSpec(
        material_id="designation",
        label="指定路線",
        dtype="categorical",
        # 国土数値情報N10/N12該当区分（emergency_transport/critical_logistics/both、
        # 外部静的データソースT51）。未該当はタイル側でプロパティ省略。
        # 改善計画T280: extractor未設定（種別ごとのper-edge kindがcompute_edge_costs_bulkへ
        # 配線されていない。is_designatedのコメントにある既存DEFERとまとめて扱う）。
        tile_property="designation",
        primary_attribute_id="designation",
    ),
    "is_designated": MaterialSpec(
        material_id="is_designated",
        label="指定路線該当（真偽）",
        dtype="boolean",
        # 改善計画T292: car_stress軸の内部軸（designation由来の調整軸）が使う簡略化された
        # 真偽値材料。指定路線の種別（emergency_transport/critical_logistics/both、材料
        # "designation"）は評価パイプライン側で種別ごとに区別して保持していない
        # （domain/designation.py: 補正量が種別によらず一律+1のため、種別を評価まで
        # 運ぶ配線を新設する理由が無い）。"designation"材料自体は将来種別を区別する軸が
        # 必要になった時点でそちらを使う（トリガー付きDEFER、設計原則9）。
        # car_stress_designation_adjustment内部軸と同じくタイル非依存
        # （評価時にdesignated_edge_idsから都度算出）。
        tile_property=None,
        primary_attribute_id="designation",
        extractor=_extract_is_designated,
    ),
    "smoothness": MaterialSpec(
        material_id="smoothness",
        label="路面の状態",
        dtype="categorical",
        # OSMのsmoothnessタグ生値（excellent/good/intermediate/bad/very_bad/horrible/
        # very_horrible/impassable、正規化: lower/btrim）。surfaceが路面「種別」なのに
        # 対し、smoothnessは実際の走行感（同じasphaltでも荒れ具合が違う等）。
        tile_property="smoothness",
        # smoothnessに対応する一次属性は未登録（bridgeと同じくレジストリ未追加）。
        extractor=_extract_smoothness,
    ),
}


def all_materials() -> list[MaterialSpec]:
    return list(MATERIAL_CATALOG.values())


def is_known_material(material_id: str) -> bool:
    return material_id in MATERIAL_CATALOG


def material_dtype(material_id: str) -> MaterialDType | None:
    """材料idのdtype（numeric/boolean）。未知の材料idにはNoneを返す
    （呼び出し側は`is_known_material`で存在確認済みの前提だが、念のため例外にはしない）。"""
    spec = MATERIAL_CATALOG.get(material_id)
    return spec.dtype if spec is not None else None
