"""区間インスペクタ（地図上の道路クリックで出す「一次属性→二次軸スコア→合成」の内訳）。

Edge単位の評価（`domain/evaluation.py`）とは入力の粒度が違う（Way1本、ルート文脈なし）
だけで、材料の値は同じ`MaterialSpec.value_sql`をway粒度のエイリアスへ当てたものを受け取る。

合成スコアはここでサーバー側が計算する。タイルへ焼き込む値に課される「解釈は
クライアントに」の制約（全ユーザー共有のキャッシュへ個別の解釈を載せられない）は、
この経路には当てはまらない——クリックのたびに1回計算する参照用途で、共有キャッシュに
乗らないため。
"""


from app.domain.axis_definitions import evaluate_axes_scalar
from app.domain.difficulty import composite_contributions, composite_difficulty
from app.domain.landcover import LandcoverPercentages, WayLandcover
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


def axis_inspector_breakdown(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool,
    materials: dict[str, object],
    way_landcover: WayLandcover | None = None,
    preference: RoutePreference | None = None,
) -> AxisInspectorResult:
    """区間インスペクタの内訳を算出する純関数。

    `materials`は`RoadGraphRepository.get_way_material_values`が返すway1本ぶんの材料値。
    way単体では求まらない材料（勾配・風）は載らず、欠損として扱われる——それを参照する軸は
    available=Falseになる。`way_landcover`は`get_feature_landcover`の戻り値で、表示用の
    内訳にだけ使う（軸の材料はSQL側が`way_landcover`から直接求めている）。
    """
    weights = (preference or RoutePreference()).weights
    # 行はあるが割合がNULL（そのラスタ構成では値なし）の場合も、行が無い場合と同じ欠損。
    landcover_percentages = way_landcover.percentages if way_landcover is not None else None
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
