"""区間インスペクタ（地図上の道路クリックで出す「一次属性→二次軸スコア→合成」の内訳）と、
軸スタジオの分布プレビューが共有するWay単位の材料解決。

Edge単位の評価（`domain/evaluation.py`）とは入力の粒度が違う（Way1本、ルート文脈なし）
だけで、材料の解決は同じ`MATERIAL_CATALOG`のextractor宣言（`resolve_materials`）を通る。

合成スコアはここでサーバー側が計算する。タイルへ焼き込む値に課される「解釈は
クライアントに」の制約（全ユーザー共有のキャッシュへ個別の解釈を載せられない）は、
この経路には当てはまらない——クリックのたびに1回計算する参照用途で、共有キャッシュに
乗らないため。
"""


from app.domain.attributes import (
    METRIC_GROUP_COUNTS,
    METRIC_GROUP_LANDCOVER,
    METRIC_GROUP_POI,
    METRIC_KEY_ACCIDENT,
    METRIC_KEY_INTERSECTION,
    WayAttributeCounts,
    WIRED_LANDCOVER_KEYS,
)
from app.domain.axis_definitions import REQUEST_DYNAMIC_MATERIAL_IDS, evaluate_axes_scalar
from app.domain.difficulty import composite_contributions, composite_difficulty
from app.domain.landcover import LandcoverPercentages, WayLandcover
from app.domain.material_catalog import MaterialExtractionContext, resolve_materials
from app.domain.route_preference import RoutePreference
from app.domain.strict_model import StrictModel


class AxisInspectorAxis(StrictModel):
    axis_id: str
    difficulty: float | None
    weight: float
    available: bool
    # この軸が合成スコアへ持ち込んでいる量（重み付き寄与度）。全軸の合計が
    # `composite_difficulty`と一致する（`domain/difficulty.py: composite_contributions`）。
    # ルート結果の`axis_contributions`と同じ読み方にするため、重みを掛ける計算は
    # サーバー側に置く。
    contribution: float | None


class AxisInspectorResult(StrictModel):
    highway: str | None
    tags: dict[str, str]
    is_designated: bool
    axes: list[AxisInspectorAxis]
    # 取得可能な軸だけの加重平均（`composite_difficulty`と同じ「データ無しは除外し
    # 残りの重みで再正規化」方針）。1つも取得できなければNone。
    composite_difficulty: float | None
    # 公開軸全体の重み合計に対する、取得できた軸の重み合計の割合（0-1）。フロントが
    # 「◯%相当の軸のみで算出」という参考値である旨を示すために使う。
    covered_weight_fraction: float | None
    # 道路周囲リングの土地被覆の内訳。軸の材料に使うのはこのうち2クラスだけだが、
    # 「この道が何で覆われているか」は軸の点数からは読み取れないため全クラスを返す。
    # 行が無い・割合がNULL（そのラスタ構成では値なし）ならNone。
    landcover: LandcoverPercentages | None = None


# 区間インスペクタ・軸スタジオのプレビューがWay1本を指すときに使う合成キー。Edge粒度の
# 呼び出しでは実際のedge_idが入る位置で、`metrics`等の1件だけの辞書を引くためだけに使う。
_WAY_SCOPE_KEY = "way"


def way_scalar_materials(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool,
    way_counts: WayAttributeCounts | None,
    accident_years_covered: int,
    landcover_percents: dict[str, float] | None = None,
    surface: str | None = None,
) -> dict[str, object]:
    """Way1本ぶんの材料値（材料id→スカラー）を組み立てる。

    Edge単位の評価経路（`compute_edge_axis_scores`・`_evaluate_axes_bulk`）と同じ
    `MATERIAL_CATALOG`のextractor宣言を、Way粒度の入力に対して適用する
    （`resolve_materials`）——材料の一覧をここへ手書きすると、材料を1つ増やしたときに
    区間インスペクタ・軸スタジオのプレビューだけ取り残される。

    Way単位のデータだけで求まる材料が対象で、ルート文脈が要る材料（勾配・風）はNoneのまま
    返す（欠損として扱われ、それを参照する軸はavailable=Falseになる）。土地被覆は
    `WIRED_LANDCOVER_KEYS`のクラスだけを受け取る（`way_landcover`の8列すべてではない）。
    """
    length_m = way_counts.length_m if way_counts is not None else 0.0
    counts: dict[str, dict[str, float]] = {}
    poi: dict[str, dict[str, float]] = {}
    if way_counts is not None:
        counts[_WAY_SCOPE_KEY] = {
            METRIC_KEY_ACCIDENT: float(way_counts.accident_count),
            METRIC_KEY_INTERSECTION: float(way_counts.intersection_count),
        }
        # 未集計（None）なら行自体を作らず、種別別の材料を欠損にする（空辞書は集計済みで
        # 0件を意味し、載っていないキーは`keyed_density_extractor(absent_key=0.0)`が0として
        # 読む。`domain/attributes.py: edge_metrics_from_bundles`と同じ意味論）。
        if way_counts.poi_counts is not None:
            poi[_WAY_SCOPE_KEY] = {k: float(v) for k, v in way_counts.poi_counts.items()}
    landcover_row = dict(landcover_percents) if landcover_percents is not None else {}
    materials = resolve_materials(
        MaterialExtractionContext(
            edge_id=_WAY_SCOPE_KEY,
            highway=highway,
            way_tags=tags,
            distance_km=length_m / 1000 if length_m > 0 else 0.0,
            # 勾配はWay単体では算出不能（ルート文脈が要る）ため空のまま渡す。
            elevation_attributes={},
            # 舗装は`osm_raw_ways.surface`の専用列で、tags jsonbには入らない
            # （`domain/osm_adapter.py: ALLOWED_WAY_TAGS`がhighway/surface/onewayを
            # 除いている）。tagsから読むと材料が常に欠損する。
            surface_attributes={_WAY_SCOPE_KEY: surface},
            designated_edge_ids={_WAY_SCOPE_KEY} if is_designated else set(),
            metrics={
                METRIC_GROUP_COUNTS: counts,
                METRIC_GROUP_POI: poi,
                METRIC_GROUP_LANDCOVER: {_WAY_SCOPE_KEY: landcover_row} if landcover_row else {},
            },
            accident_years_covered=accident_years_covered,
        )
    )
    # 動的材料（風）はextractorを持たない完全ベクトル化計算のため、ここでは常に欠損。
    # キー自体を置いて「材料としては存在するが値が無い」ことを明示する
    # （`evaluate_axis_scalar`はキーの有無と値Noneを同じ欠損として扱うため挙動は同じ）。
    materials.update({material_id: None for material_id in REQUEST_DYNAMIC_MATERIAL_IDS})
    return materials


def axis_inspector_breakdown(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool,
    way_counts: WayAttributeCounts | None,
    accident_years_covered: int,
    way_landcover: WayLandcover | None = None,
    preference: RoutePreference | None = None,
    surface: str | None = None,
) -> AxisInspectorResult:
    """区間インスペクタの内訳を算出する純関数。`way_counts`は
    `RoadGraphRepository.get_way_attribute_counts`の戻り値で、Noneなら事故密度・
    停止密度は算出不能（available=False）として扱う。`way_landcover`は
    `RoadGraphRepository.get_way_landcover`の戻り値で、Noneまたは`percentages`がNone
    （そのラスタ構成では値なし）なら、土地被覆を参照する軸は算出不能として扱う。
    `WIRED_LANDCOVER_KEYS`のクラスだけを材料へ渡す。
    """
    weights = (preference or RoutePreference()).weights
    # 行はあるが割合がNULL（そのラスタ構成では値なし）の場合も、行が無い場合と同じ欠損。
    landcover_percentages = way_landcover.percentages if way_landcover is not None else None
    materials = way_scalar_materials(
        highway, tags, is_designated, way_counts, accident_years_covered,
        (
            {key: getattr(landcover_percentages, key) for key in WIRED_LANDCOVER_KEYS}
            if landcover_percentages is not None
            else None
        ),
        surface,
    )
    scores, _ = evaluate_axes_scalar(materials)

    scored_weights = [(score, weights.get(axis_id, 0.0)) for axis_id, score in scores.items()]
    contributions = composite_contributions(scored_weights)
    axes = [
        AxisInspectorAxis(
            axis_id=axis_id,
            difficulty=score,
            weight=weights.get(axis_id, 0.0),
            available=score is not None,
            contribution=contribution,
        )
        for (axis_id, score), contribution in zip(scores.items(), contributions, strict=True)
    ]

    composite = composite_difficulty(scored_weights)
    total_weight = sum(weights.values())
    covered_weight = sum(weights.get(axis_id, 0.0) for axis_id, score in scores.items() if score is not None)
    covered_fraction = round(covered_weight / total_weight, 3) if total_weight > 0 else None

    return AxisInspectorResult(
        highway=highway,
        tags=tags,
        is_designated=is_designated,
        axes=axes,
        composite_difficulty=composite,
        covered_weight_fraction=covered_fraction,
        landcover=landcover_percentages,
    )
