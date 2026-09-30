"""区間インスペクタ（地図上の道路クリックで出す「一次属性→二次軸スコア→合成」の内訳）。

Edge単位の評価（`domain/evaluation.py`）とは入力の粒度が違う（Way1本、ルート文脈なし）
だけで、材料の値は同じ`MaterialSpec.value_sql`をway粒度のエイリアスへ当てたものを受け取る。

合成スコアはここでサーバー側が計算する。タイルへ焼き込む値に課される「解釈は
クライアントに」の制約（全ユーザー共有のキャッシュへ個別の解釈を載せられない）は、
この経路には当てはまらない——クリックのたびに1回計算する参照用途で、共有キャッシュに
乗らないため。
"""


from app.domain.axis_definitions import evaluate_axes_values
from app.domain.difficulty import composite_difficulty
from app.domain.landcover import LandcoverPercentages
from app.domain.route_preference import RoutePreference
from app.domain.strict_model import StrictModel


class AxisInspectorAxis(StrictModel):
    axis_id: str
    #: 材料が足りず評価できなければNone。
    difficulty: float | None
    weight: float
    # この軸が合成スコアへ持ち込んでいる量（重み付き寄与度、`composite_difficulty`と同じ
    # 分母で正規化した値）。ルート結果の`axis_contributions`と同じ読み方にするため、
    # 重みを掛ける計算はサーバー側に置く。
    contribution: float | None


class InspectorComposite(StrictModel):
    """取得できた軸だけの加重平均（`composite_difficulty`と同じ「データ無しは除外し残りの重みで
    再正規化」方針）と、それが公開軸全体の重み合計のうち何割の軸から出たか（0-1）。フロントは
    「◯%相当の軸のみで算出」という参考値である旨を示すために割合を使う。"""

    value: float
    covered_weight_fraction: float


class AxisInspectorResult(StrictModel):
    highway: str | None
    tags: dict[str, str]
    axes: list[AxisInspectorAxis]
    #: 1つも取得できなければNone。
    composite_difficulty: InspectorComposite | None
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
    scores = {
        axis_id: values[0]
        for axis_id, values in evaluate_axes_values({key: [value] for key, value in materials.items()}, 1).items()
    }

    composite, contributions = composite_difficulty(scores, weights)
    axes = [
        AxisInspectorAxis(
            axis_id=axis_id,
            difficulty=score,
            weight=weights.get(axis_id, 0.0),
            contribution=contributions[axis_id],
        )
        for axis_id, score in scores.items()
    ]

    return AxisInspectorResult(
        highway=highway,
        tags=tags,
        axes=axes,
        composite_difficulty=None if composite is None else _composite(composite, scores, weights),
        landcover=landcover,
    )


def _composite(value: float, scores: dict[str, float | None], weights: dict[str, float]) -> InspectorComposite:
    # 合成が求まるのは得点のある軸の重みの合計が正のときだけなので、全体の重みの合計も正。
    covered_weight = sum(weights.get(axis_id, 0.0) for axis_id, score in scores.items() if score is not None)
    return InspectorComposite(
        value=value, covered_weight_fraction=round(covered_weight / sum(weights.values()), 3)
    )
