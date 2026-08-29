"""周回ルート生成の戦略層（エンジン非依存）。

「8方位×固定半径で経由地点を決め、各方位の周回を距離許容範囲でフィルタし、
RouteScorerで総合スコアを付けて並べ替える」という周回生成戦略を1箇所に持つ。
経由地点間の実際の経路計算と評価値（標高・風・路面）の取得方法はエンジン
（`LoopRoutingEngine`実装）へ委譲し、`config.py`の`routing_engine`設定で
`OpenRouteServiceEngine`（openrouteservice委譲）と`RoadGraphEngine`
（自前Road Graph + scipy.sparse.csgraph Dijkstra、改善計画T220でNetworkXから移行済み。
road_graph_engine.py参照）を切り替える。

この分割により、周回戦略側の将来拡張（適応的な半径調整・道路実データからの
候補地点選定・候補数の増加等、仕様書7-11章・docs/architecture.md 5章）は
エンジンに関わらず1箇所の変更で済む。

エンジンの契約（LoopRoutingEngine）:
- `engine_name`: レスポンスの`engine`フィールドに入る識別子
- `prepare(origin, radius_km)`: 1リクエスト分の共有準備（Road Graph構築等）。
  候補生成が不可能な場合はNoneを返す（→ 空の候補リスト）
- `trace_loop(context, waypoints, bearing)`: 1方位分の周回経路を引き、距離と
  エンジン固有の中間データを`TracedLoop`で返す。失敗はRoutingErrorをraiseする
  （その方位はスキップされる）
- `evaluate_loops(context, traced, start_time)`: 距離フィルタを通過した候補
  **だけ**に標高・風・路面の評価を行い、完全な`RouteCandidate`群を返す。
  棄却済み候補に外部API問い合わせを浪費しないための2段階分割
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.domain.difficulty import distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.geo import compass_label, destination_point
from app.domain.route import Coordinates, RouteCandidate, merge_axis_difficulties
from app.services.route_scorer import RouteScorer

# ルート生成のステージ別サマリログ(方針は docs/logging.md)。1リクエスト=1行のINFOで
# prepare/trace/evaluateの所要時間と候補の減り方(8方位→trace成功→距離フィルタ通過)を残し、
# 「候補が少ない/生成が遅い」の切り分けをRenderのログだけで完結できるようにする。
# 候補0件(ユーザーに何も返せない)はWARNINGへ昇格し、方位別の失敗理由はDEBUGで補足する。
logger = logging.getLogger("ridecompass.generate")

# 8方位（北を0として時計回り）
DIRECTIONS_DEG = [0, 45, 90, 135, 180, 225, 270, 315]

# 半径ヒューリスティック: 仕様書7章の目安（30kmなら半径10〜15km程度）に近い値。
# 適応的な探索は行わないため、実際の道路網次第で距離のばらつきが生じる（既知の制約）。
RADIUS_RATIO = 1 / 3

# サーバーのローカル時刻＝Asia/Tokyoという簡易近似（Open-Meteoのhourlyもtimezone=Asia/Tokyo
# 指定でnaiveなローカル時刻文字列を返すため整合している。詳細はdocs/architecture.md参照）。
# 日本にDSTが無いことを利用して固定オフセットで表現し、追加依存（tzdata）なしで
# datetimeをtz-awareにする。
JST = timezone(timedelta(hours=9))


@dataclass
class TracedLoop:
    """trace_loopの結果。距離フィルタに必要な情報と、evaluate_loopsが完全な
    RouteCandidateを組み立てるためのエンジン固有の中間データを運ぶ。

    改善計画T364: bearing=Noneは経由地(waypoints)指定ルートを表す。8方位探索と異なり
    「向き」という概念を持たず、ユーザーが指定した訪問順序をそのまま保持する必要がある
    （road_graph_engine.py: _build_best_candidateの逆回り合成をスキップする判定に使う）。
    """

    bearing: int | None
    distance_km: float
    data: Any


def candidate_identity(bearing: int | None) -> dict[str, str]:
    """方位から候補のid・方位ラベルを導出する（両エンジンで共通の命名規則）。
    改善計画T364: bearing=None（経由地指定ルート）は固定のid・ラベルを返す。"""
    if bearing is None:
        return {"id": "route-waypoints", "direction_label": "経由地ルート"}
    return {"id": f"route-{bearing:03d}", "direction_label": compass_label(bearing)}


class LoopRoutingEngine(Protocol):
    engine_name: str

    async def prepare(
        self, origin: Coordinates, radius_km: float, waypoints: list[Coordinates] | None = None
    ) -> Any | None: ...

    async def trace_loop(
        self, context: Any, waypoints: list[Coordinates], bearing: int | None
    ) -> TracedLoop: ...

    async def evaluate_loops(
        self, context: Any, traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]: ...


class RouteGenerator:
    """周回ルート候補の生成戦略。経路計算と評価はengineへ委譲する。"""

    def __init__(self, engine: LoopRoutingEngine, route_scorer: RouteScorer):
        self._engine = engine
        self._route_scorer = route_scorer

    @property
    def engine_name(self) -> str:
        return self._engine.engine_name

    async def generate_loops(
        self,
        origin: Coordinates,
        distance_km: float,
        distance_tolerance_km: float,
    ) -> list[RouteCandidate]:
        radius_km = distance_km * RADIUS_RATIO
        started = time.monotonic()
        # 常時出るサマリログ用に座標を2桁(≈1km)へ丸める(debug_log.pyの方針と同じ)。
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"

        context = await self._engine.prepare(origin, radius_km)
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            logger.warning(
                "generate engine=%s origin=%s target_km=%.1f -> no context (road data unavailable) prepare_ms=%d",
                self.engine_name, origin_label, distance_km, prepare_ms,
            )
            return []

        trace_started = time.monotonic()
        results = await asyncio.gather(
            *(
                self._engine.trace_loop(context, self._loop_waypoints(origin, bearing, radius_km), bearing)
                for bearing in DIRECTIONS_DEG
            ),
            return_exceptions=True,
        )
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        traced_all: list[TracedLoop] = []
        failed_bearings: list[int] = []
        for bearing, result in zip(DIRECTIONS_DEG, results):
            if isinstance(result, TracedLoop):
                traced_all.append(result)
            elif isinstance(result, RoutingError):
                # 個々の方位の失敗は準正常(道路網次第で起きる)。件数はINFOサマリに含め、
                # 理由はDEBUGで補足する。全滅した場合のみ後段でWARNINGになる。
                failed_bearings.append(bearing)
                logger.debug("trace bearing=%d failed: %s", bearing, result)
            elif isinstance(result, BaseException):
                # RoutingError以外はエンジンの不具合の可能性が高いため、スタックトレース付きで残す。
                failed_bearings.append(bearing)
                logger.error("trace bearing=%d unexpected error", bearing, exc_info=result)

        traced = [t for t in traced_all if abs(t.distance_km - distance_km) <= distance_tolerance_km]
        filtered_out = len(traced_all) - len(traced)
        for t in traced_all:
            if abs(t.distance_km - distance_km) > distance_tolerance_km:
                logger.debug(
                    "distance filter rejected bearing=%d distance_km=%.1f (target=%.1f±%.1f)",
                    t.bearing, t.distance_km, distance_km, distance_tolerance_km,
                )
        # 評価前に目標距離に近い順へ並べておく（最終順序はtotal_scoreで決まるが、
        # 評価順・candidates内の並びを安定させるため）。
        traced.sort(key=lambda t: abs(t.distance_km - distance_km))

        if not traced:
            logger.warning(
                "generate engine=%s origin=%s target_km=%.1f -> no candidates "
                "(trace_ok=%d/%d trace_failed=%s filtered_out=%d) prepare_ms=%d trace_ms=%d",
                self.engine_name, origin_label, distance_km,
                len(traced_all), len(DIRECTIONS_DEG), failed_bearings, filtered_out,
                prepare_ms, trace_ms,
            )
            return []

        evaluate_started = time.monotonic()
        start_time = datetime.now(JST)
        candidates = await self._engine.evaluate_loops(context, traced, start_time)
        candidates = [self._with_overall_difficulty(c) for c in candidates]
        candidates = [self._with_axis_difficulties(c) for c in candidates]

        candidates = self._route_scorer.score(candidates, distance_km)
        candidates.sort(key=lambda c: c.total_score if c.total_score is not None else -1, reverse=True)
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate engine=%s origin=%s target_km=%.1f -> candidates=%d "
            "trace_ok=%d/%d trace_failed=%s filtered_out=%d "
            "prepare_ms=%d trace_ms=%d evaluate_ms=%d total_ms=%d",
            self.engine_name, origin_label, distance_km, len(candidates),
            len(traced_all), len(DIRECTIONS_DEG), failed_bearings, filtered_out,
            prepare_ms, trace_ms, evaluate_ms, total_ms,
        )
        return candidates

    async def generate_via_waypoints(
        self,
        origin: Coordinates,
        waypoints: list[Coordinates],
        distance_km: float,
        destination: Coordinates | None = None,
    ) -> list[RouteCandidate]:
        """改善計画T364/T365: ユーザーが指定した経由地（中継地）を順に通る単一経路を生成する。

        `generate_loops`の8方位探索・距離許容フィルタとは独立した経路（経由地が
        あれば、目的は「近い距離の周回」ではなく「指定した地点を通ること」自体のため）。
        `distance_km`はRoad Graph取得bboxの見積り半径にのみ使う参考値で、実際の距離は
        経由地の配置で決まる（距離フィルタは行わない）。`destination`省略時は起点に
        戻る周回（従来のT364挙動）、指定時は起点に戻らず目的地で終わる片道ルートになる
        （T365、`candidate_identity`とは別に終点到達後にid/direction_labelを
        route-destination/目的地ルートへ上書きする）。
        """
        radius_km = distance_km * RADIUS_RATIO
        started = time.monotonic()
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"
        end_point = destination if destination is not None else origin
        full_waypoints = [origin, *waypoints, end_point]
        # 改善計画T365: bboxが目的地もカバーするよう、prepareへ渡す点集合に含める
        # （経由地のみのbbox計算は`_bbox_covering_points`、road_graph_engine.py参照）。
        bbox_points = [*waypoints, destination] if destination is not None else waypoints

        context = await self._engine.prepare(origin, radius_km, waypoints=bbox_points)
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            logger.warning(
                "generate(via_waypoints) engine=%s origin=%s waypoints=%d destination=%s -> no context prepare_ms=%d",
                self.engine_name, origin_label, len(waypoints), destination is not None, prepare_ms,
            )
            return []

        trace_started = time.monotonic()
        try:
            traced = await self._engine.trace_loop(context, full_waypoints, bearing=None)
        except RoutingError as exc:
            logger.warning(
                "generate(via_waypoints) engine=%s origin=%s waypoints=%d destination=%s -> trace failed: %s",
                self.engine_name, origin_label, len(waypoints), destination is not None, exc,
            )
            return []
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        evaluate_started = time.monotonic()
        start_time = datetime.now(JST)
        candidates = await self._engine.evaluate_loops(context, [traced], start_time)
        candidates = [self._with_overall_difficulty(c) for c in candidates]
        candidates = [self._with_axis_difficulties(c) for c in candidates]
        if destination is not None:
            candidates = [
                c.model_copy(update={"id": "route-destination", "direction_label": "目的地ルート"})
                for c in candidates
            ]
        # 改善計画T364: 候補は常に1件のため、RouteScorer（候補集合内でのmin-max正規化）は
        # 呼ばない。domain/scoring.py: normalize_min_maxはlo==hiのとき常に中立100点を返す
        # ため、候補1件に対して呼ぶと「常に満点」という誤解を招く数値になってしまう。
        # total_scoreはRouteCandidateで元々None許容であり、frontend側（RouteList.tsx）は
        # 既にtotal_score != nullで無表示に倒す分岐を持つ。
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate(via_waypoints) engine=%s origin=%s waypoints=%d destination=%s target_km=%.1f -> distance_km=%.1f "
            "prepare_ms=%d trace_ms=%d evaluate_ms=%d total_ms=%d",
            self.engine_name, origin_label, len(waypoints), destination is not None, distance_km, traced.distance_km,
            prepare_ms, trace_ms, evaluate_ms, total_ms,
        )
        return candidates

    @staticmethod
    def _with_overall_difficulty(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsの区間difficultyから距離加重平均のルート単位絶対基準集約値を付与する
        （研究インターフェース改善 §10-7、両エンジン共通のためengine実装側には持たせない）。"""
        if not candidate.segments:
            return candidate
        overall = distance_weighted_difficulty(
            [(s.difficulty, s.distance_km) for s in candidate.segments]
        )
        return candidate.model_copy(update={"overall_difficulty": overall})

    @staticmethod
    def _with_axis_difficulties(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsのaxis_difficulties（区間ごとのaxis_id→difficulty）をルート全区間へ
        集約し、overall_difficultyと対になるルート全体版を付与する（改善計画T402）。
        既存の`merge_axis_difficulties`（domain/route.py、_merge_segment_bin用に元々あった
        もの）を候補全区間に対して1回適用するだけで得られ、新しい計算式は不要。"""
        if not candidate.segments:
            return candidate
        axis_difficulties = merge_axis_difficulties(candidate.segments)
        return candidate.model_copy(update={"axis_difficulties": axis_difficulties})

    @staticmethod
    def _loop_waypoints(origin: Coordinates, bearing: int, radius_km: float) -> list[Coordinates]:
        """方位bearingの周回経由地点列: 起点→θ方向に半径R→θ+45°方向に半径R→起点。"""
        waypoint_a = destination_point(origin, bearing, radius_km)
        waypoint_b = destination_point(origin, (bearing + 45) % 360, radius_km)
        return [origin, waypoint_a, waypoint_b, origin]
