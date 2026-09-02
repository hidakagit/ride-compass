"""周回ルート生成の戦略層（エンジン非依存）。

「8方位×固定半径で経由地点を決め、各方位の周回を距離許容範囲でフィルタし、
overall_difficulty（絶対基準0-100の総合難易度）昇順で並べ替える」という周回生成戦略を
1箇所に持つ。
経由地点間の実際の経路計算と評価値（標高・風・路面）の取得方法はエンジン
（`LoopRoutingEngine`実装）へ委譲する。現在の唯一の実装は`RoadGraphEngine`
（自前Road Graph + scipy.sparse.csgraph Dijkstra、road_graph_engine.py参照）。

この分割により、周回戦略側の将来拡張（適応的な半径調整・道路実データからの
候補地点選定・候補数の増加等、仕様書7-11章・docs/architecture.md 5章）は
エンジンに関わらず1箇所の変更で済む。

エンジンの契約（LoopRoutingEngine）:
- `engine_name`: レスポンスの`engine`フィールドに入る識別子
- `prepare(origin, radius_km)`: 1リクエスト分の共有準備（Road Graph構築等）。
  候補生成が不可能な場合はNoneを返す（→ 空の候補リスト）
- `trace_loop(context, waypoints, bearing, max_distance_km=None)`: 1方位分の周回経路を
  引き、距離とエンジン固有の中間データを`TracedLoop`で返す。失敗はRoutingErrorを
  raiseする（その方位はスキップされる）。改善計画T540: `max_distance_km`
  （`distance_km + distance_tolerance_km`、8方位探索[bearing指定]のみ渡す）を
  超えることが残りレグの下限距離から確定した時点で、エンジンは残りレグの探索を
  省略し`RouteDistanceExceededError`をraiseしてよい（`generate_loops`側は従来の
  距離フィルタ棄却と同じ`filtered_out`集計に含める）
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
from app.domain.errors import RouteDistanceExceededError, RoutingError
from app.domain.geo import compass_label, destination_point
from app.domain.route import Coordinates, RouteCandidate, merge_axis_difficulties

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
    """方位から候補のid・方位ラベルを導出する（エンジン非依存の共通命名規則）。
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
        self,
        context: Any,
        waypoints: list[Coordinates],
        bearing: int | None,
        max_distance_km: float | None = None,
    ) -> TracedLoop: ...

    async def evaluate_loops(
        self, context: Any, traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]: ...


class RouteGenerator:
    """周回ルート候補の生成戦略。経路計算と評価はengineへ委譲する。"""

    def __init__(self, engine: LoopRoutingEngine):
        self._engine = engine
        # 改善計画T441: candidatesが空になったときの原因（人間可読な要約、下記の
        # logger.warning行と同じ情報源）。呼び出し側（routes.py: _run_generate_job）が
        # RouteGenerateResponse.no_candidates_reasonへそのまま転記し、GUI（デバッグログ・
        # 候補0件時のメッセージ）から確認できるようにする——実際に本番で「候補0件」が
        # 発生した際、原因を切り分ける手段がサーバーログのSSH閲覧しか無かった実インシデント
        # を受けて追加した。インスタンスは`api/dependencies.py: _build_route_generation_setup`
        # がリクエストごとに新規生成するため、インスタンス属性として持っても並行リクエスト間で
        # 競合しない。
        self.last_no_candidates_reason: str | None = None

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
        self.last_no_candidates_reason = None

        context = await self._engine.prepare(origin, radius_km)
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            logger.warning(
                "generate engine=%s origin=%s target_km=%.1f -> no context (road data unavailable) prepare_ms=%d",
                self.engine_name, origin_label, distance_km, prepare_ms,
            )
            self.last_no_candidates_reason = (
                f"起点{origin_label}付近の道路データが未整備のため、候補を生成できませんでした。"
                "対応エリア外の可能性があります。"
            )
            return []

        # 改善計画T540: 距離許容範囲の上限（distance_km + distance_tolerance_km）を
        # engine.trace_loopへ渡す。エンジンは残りレグの下限距離からこの上限を確実に
        # 超えると分かった時点でRouteDistanceExceededErrorをraiseし、無駄な残りレグの
        # 探索を省略できる（8方位探索[bearing指定]のみ。経由地指定ルートは
        # generate_via_waypoints側の別経路で距離フィルタ自体を行わないため対象外）。
        max_distance_km = distance_km + distance_tolerance_km
        trace_started = time.monotonic()
        results = await asyncio.gather(
            *(
                self._engine.trace_loop(
                    context, self._loop_waypoints(origin, bearing, radius_km), bearing,
                    max_distance_km=max_distance_km,
                )
                for bearing in DIRECTIONS_DEG
            ),
            return_exceptions=True,
        )
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        traced_all: list[TracedLoop] = []
        failed_bearings: list[int] = []
        # 改善計画T540: エンジンが早期打ち切りした方位の件数。全レグ完了後の距離フィルタ
        # （下のfiltered_out算出）で棄却されていたはずの候補と同じ集合のため、
        # 従来のfiltered_outへ合算し、no_candidates_reasonの文言も従来どおり
        # 「指定距離から外れました」に寄せる（区別して新しい文言を増やさない）。
        early_filtered_out = 0
        for bearing, result in zip(DIRECTIONS_DEG, results):
            if isinstance(result, TracedLoop):
                traced_all.append(result)
            elif isinstance(result, RouteDistanceExceededError):
                early_filtered_out += 1
                logger.debug("distance filter rejected bearing=%d (early cutoff): %s", bearing, result)
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
        # 改善計画T540: 全レグ完了後の距離フィルタ棄却（post_hoc）＋早期打ち切り
        # （early_filtered_out）を合算した値を、以降のログ・no_candidates_reasonへ渡す
        # filtered_outとして扱う（打ち切りが距離フィルタと同じ集合を棄却するという
        # 前提のもと、呼び出し元からは区別しない）。
        post_hoc_filtered_out = len(traced_all) - len(traced)
        filtered_out = post_hoc_filtered_out + early_filtered_out
        for t in traced_all:
            if abs(t.distance_km - distance_km) > distance_tolerance_km:
                logger.debug(
                    "distance filter rejected bearing=%d distance_km=%.1f (target=%.1f±%.1f)",
                    t.bearing, t.distance_km, distance_km, distance_tolerance_km,
                )
        # 評価前に目標距離に近い順へ並べておく（最終順序はoverall_difficultyで決まるが、
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
            self.last_no_candidates_reason = self._describe_no_traced_reason(
                distance_km, distance_tolerance_km, failed_bearings, filtered_out,
            )
            return []

        evaluate_started = time.monotonic()
        start_time = datetime.now(JST)
        candidates = await self._engine.evaluate_loops(context, traced, start_time)
        candidates = [self._with_overall_difficulty(c) for c in candidates]
        candidates = [self._with_axis_difficulties(c) for c in candidates]

        # 改善計画T548: 候補タブの並び順はoverall_difficulty（絶対基準0-100の総合難易度）
        # 昇順（易しい候補が先頭）。算出不能（None）の候補は末尾へ回す。
        candidates.sort(
            key=lambda c: c.overall_difficulty if c.overall_difficulty is not None else float("inf")
        )
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
        self.last_no_candidates_reason = None
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
            self.last_no_candidates_reason = (
                f"起点{origin_label}付近の道路データが未整備のため、候補を生成できませんでした。"
                "対応エリア外の可能性があります。"
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
            self.last_no_candidates_reason = (
                "指定した経由地・目的地を通る経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
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
    def _describe_no_traced_reason(
        distance_km: float,
        distance_tolerance_km: float,
        failed_bearings: list[int],
        filtered_out: int,
    ) -> str:
        """改善計画T441: generate_loopsが`traced`空で候補0件になったときの人間可読な要約を
        組み立てる（logger.warningと同じ情報源から、RouteGenerateResponse.
        no_candidates_reason用に生成する）。"""
        parts = []
        if failed_bearings:
            parts.append(f"{len(failed_bearings)}方位で経路探索に失敗しました（除外設定をご確認ください）")
        if filtered_out:
            parts.append(
                f"{filtered_out}方位は指定距離（{distance_km:.1f}km±{distance_tolerance_km:.1f}km）から外れました"
            )
        if not parts:
            # trace_ok==0かつfailed_bearingsも空という理論上到達しないはずの状態への保険。
            parts.append("8方位すべてで経路候補が得られませんでした")
        return "、".join(parts) + "。距離や除外する道路の設定を変えてお試しください。"

    @staticmethod
    def _with_overall_difficulty(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsの区間difficultyから距離加重平均のルート単位絶対基準集約値を付与する
        （研究インターフェース改善 §10-7、エンジン非依存のためengine実装側には持たせない）。"""
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
