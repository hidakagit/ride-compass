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
from app.domain.landcover import LandcoverPercentages
from app.domain.route_preference import RoutePreference
from app.domain.strict_model import StrictModel


class AxisInspectorAxis(StrictModel):
    axis_id: str
    difficulty: float | None
    weight: float
    available: bool
    # この軸が合成スコアへ持ち込んでいる量（重み付き寄与度、`composite_difficulty`と同じ
    # 分母で正規化した値）。ルート結果の`axis_contributions`と同じ読み方にするため、
    # 重みを掛ける計算はサーバー側に置く。
    contribution: float | None


class AxisInspectorResult(StrictModel):
    highway: str | None
    tags: dict[str, str]
    axes: list[AxisInspectorAxis]
    # 取得可能な軸だけの加重平均（`composite_difficulty`と同じ「データ無しは除外し
    # 残りの重みで再正規化」方針）。1つも取得できなければNone。
    composite_difficulty: float | None
    # 公開軸全体の重み合計に対する、取得できた軸の重み合計の割合（0-1）。フロントが
    # 「◯%相当の軸のみで算出」という参考値である旨を示すために使う。
    covered_weight_fraction: float | None
    # 道路周囲リングの土地被覆の内訳。軸の材料に使うのは一部のクラスだけだが、
    # 「この道が何で覆われているか」は軸の点数からは読み取れないため全クラスを返す。
    # 行が無い・割合がNULL（そのラスタ構成では値なし）ならNone。
    landcover: LandcoverPercentages | None = None


def axis_inspector_breakdown(
    highway: str | None,
    tags: dict[str, str],
    materials: dict[str, object],
    landcover: LandcoverPercentages | None,
    preference: RoutePreference,
) -> AxisInspectorResult:
    """区間インスペクタの内訳を算出する純関数。

    `materials`は`RoadGraphRepository.get_way_material_values`が返すway1本ぶんの材料値に、
    進行方向に依存する材料（勾配・風）を呼び出し側が引いて足したもの。足されなかった材料は
    欠損として扱われ、それを参照する軸はavailable=Falseになる。`landcover`は表示用の
    内訳にだけ使う——軸の材料はSQL側が同じ行から直接求めている。

    重みは呼び出し側が渡す。ここで既定を組み立てると、呼び出し側が渡し忘れた重みが
    画面へ出たまま誰も気づかない。
    """
    weights = preference.weights
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
        axes=axes,
        composite_difficulty=composite,
        covered_weight_fraction=covered_fraction,
        landcover=landcover,
    )
