from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import (
    EdgeCostResult,
    RoutePreference,
    compute_edge_costs_bulk,
)
from app.domain.graph import RoadGraphLike
from app.domain.weather import WeatherConditions


def load_route_preference() -> RoutePreference:
    """既定のRoute Preference（重み）を返す（仕様書27-28章）。

    改善計画T316: 以前は`route_preference.yaml`（axis_id 7件を固定で書いた手書き
    ミラー）から読んでいたが、軸スタジオ（T270）で公開軸の集合・default_weightを
    自由に増減できるようになった設計と根本的に矛盾していた——公開軸の集合が
    元の7件から変わるたびに、YAML側の固定キー集合と`RoutePreference`のバリデーション
    （未知のaxis_idを拒否、`domain/evaluation.py`参照）が食い違い、「route_preference
    未上書きでルート生成すると即500」という実障害を起こした（2026-08-25、ユーザーが
    軸スタジオで一部軸を意図的に非公開にした際に発覚）。`export_openapi.py`の
    `preference_defaults`が同種の手書きミラーを既に`default_axis_weights()`
    （`AXIS_DEFINITIONS`が唯一の情報源）へ置き換え済みだったのと同じ理由で、
    こちらも追従させる。`RoutePreference.weights`の`default_factory`が
    `default_axis_weights()`のため、単に既定値を使うだけでよい。
    """
    return RoutePreference()


class EvaluationService:
    """Evaluation Engineのオーケストレーション層（仕様書26章）。

    I/Oは行わない。属性の取得自体はPhase 3の`ElevationAttributeService`・
    `GraphService.get_or_build_graph_with_attributes`が担当し、ここでは
    既に取得済みのRoadGraph・属性からEdge Costを算出するのみ。探索コスト算出の
    既定経路は`RoadGraphEngine`のタイル単位静的スコア行列（`domain/evaluation.py:
    build_static_edge_score_matrix`）で本クラスを経由しない——`evaluate_graph`は
    テスト・ベンチマーク（`compute_edge_costs_bulk`との出力一致を確認する回帰オラクル）
    向けに残るオーケストレーション層。
    """

    def __init__(self, preference: RoutePreference):
        self._preference = preference

    def evaluate_graph(
        self,
        graph: RoadGraphLike,
        elevation_attributes: dict[str, ElevationAttribute],
        surface_attributes: dict[str, str | None],
        preference: RoutePreference,
        weather: WeatherConditions | None = None,
        stop_counts: dict[str, int] | None = None,
        way_tags: dict[str, dict[str, str]] | None = None,
        intersection_counts: dict[str, int] | None = None,
        accident_counts: dict[str, int] | None = None,
        accident_years_covered: int = 0,
        designated_edge_ids: set[str] | None = None,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
        hard_filters: frozenset[str] | None = None,
    ) -> dict[str, EdgeCostResult]:
        # preferenceは呼び出し元が必ず明示的に渡す（self._preferenceを直接書き換えると
        # リクエスト間で共有される状態を汚染するため、呼び出し元がmodel_copyしたコピーを
        # こちらへ渡す設計）。
        # penalty_strength（改善計画T218・T12 ADR原則1）はコスト式の割増率の強さを
        # 調整するリクエストパラメータ（既定1.0）。domain/evaluation.py:
        # compute_cost_from_axis_scores参照。
        # max_average_grade_percent（改善計画T218a・T12 ADR原則5）は0次ハードフィルタの
        # 勾配しきい値（既定None＝除外しない）。domain/evaluation.py: is_edge_allowed参照。
        # hard_filters（改善計画T266）は0次フィルタ名（no_bicycle/motorway/trunk）の
        # 個別ON/OFF上書き（既定None＝DEFAULT_HARD_FILTERS＝全フィルタ有効）。
        stop_counts = stop_counts or {}
        designated_edge_ids = designated_edge_ids or set()
        # 改善計画T221 Stage B: RoutePreference自体がaxis_idキーの重み辞書を持つため
        # そのまま渡す（T220で導入した「graph全体で1回だけ重みを解決する」意図は不変）。
        weights = preference.weights
        # 改善計画T240: compute_edge_costを1件ずつ呼ぶPythonループから、numpyベクトル化した
        # compute_edge_costs_bulkへ切り替えた（Edge数万〜十数万件規模での実行時間短縮）。
        # スカラー版compute_edge_costは削除せず、tests/test_evaluation_bulk.pyの回帰
        # オラクルとして存続させている。
        return compute_edge_costs_bulk(
            graph,
            elevation_attributes,
            surface_attributes,
            preference,
            weather=weather,
            stop_counts=stop_counts,
            way_tags=way_tags,
            intersection_counts=intersection_counts,
            accident_counts=accident_counts,
            accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids,
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
            weights=weights,
            hard_filters=hard_filters,
        )
