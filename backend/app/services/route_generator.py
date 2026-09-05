"""周回ルート生成の戦略層（エンジン非依存）。

「起点からの一対全最短経路木（公開軸の重み付きコスト）で目標距離の半分付近に到達する
折返し点を、往路の軸的な良さの順に選び、往路と別の復路を探索して周回にし、距離許容範囲で
フィルタして、overall_difficulty（絶対基準0-100の総合難易度）昇順の上位`max_routes`件を
返す」という周回生成戦略（フロンティア方式）を1箇所に持つ。
折返し点の選定・経路計算・評価値（標高・風・路面）の取得方法はエンジン
（`LoopRoutingEngine`実装）へ委譲する。現在の唯一の実装は`RoadGraphEngine`
（自前Road Graph + rustworkx A*/scipy一対全Dijkstra、road_graph_engine.py参照）。

候補の形は公開軸の重み配分で決まる（例: 自転車インフラの重みを100%にすると、往路が
自転車インフラ上を通る折返し点ほど上位に選ばれる）。距離は目標±`distance_tolerance_km`の
厳格フィルタであり、スコアとは混ぜない。

エンジンの契約（LoopRoutingEngine）:
- `engine_name`: レスポンスの`engine`フィールドに入る識別子
- `prepare(origin, radius_km)`: 1リクエスト分の共有準備（Road Graph構築等）。
  候補生成が不可能な場合はNoneを返す（→ 空の候補リスト）
- `select_loop_turnarounds(context, distance_km, distance_tolerance_km, pool_size)`:
  折返し点候補を、往路の軸的な良さの順に最大`pool_size`件返す（互いに似た往路を持つ
  候補は間引き済み）。候補が無ければ空リスト
- `trace_loop_from_turnaround(context, turnaround)`: 往路（折返し点まで）＋往路と別の
  復路（起点まで）の周回を引き、距離とエンジン固有の中間データを`TracedLoop`で返す。
  失敗はRoutingErrorをraiseする（その候補はスキップされる）
- `select_via_nodes(context, destination, max_routes)`: 経由地の無い目的地ルート
  （起点→目的地）のvia-node方式代替経路選定。互いに異なる経路を最大
  `max_routes`件、`TracedLoop`（`bearing=None`）のリストで返す。両方向の一対全木の
  経路復元だけで確定するため個々の候補が失敗することは無く、`select_loop_turnarounds`
  と違って戻り値がそのまま最終候補になる（`trace_loop_from_turnaround`に相当する
  候補ごとの再探索ステップが無い）
- `trace_loop(context, waypoints, bearing)`: 経由地・目的地指定ルート（`generate_via_waypoints`）
  用。指定した地点列を順に結ぶ経路を`TracedLoop`で返す
- `evaluate_loops(context, traced, start_time)`: 距離フィルタを通過した候補
  **だけ**に実ジオメトリ取得・標高・風・路面の評価を行い、完全な`RouteCandidate`群を返す。
  棄却済み候補にDB/外部API問い合わせを浪費しないための2段階分割
- `is_loop_too_similar(context, candidate, accepted)`: `candidate`が`accepted`
  （距離フィルタ・本判定を既に通過した候補群）のいずれかと、周回全体（往路＋復路、
  進行方向は無視）でエンジン固有の閾値を超えて重複するか。
  戦略層は`TracedLoop.data`の中身を知らないため、重複判定自体もエンジンへ委譲する
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.domain.difficulty import difficulty_load, distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.geo import compass_label
from app.domain.route import (
    Coordinates,
    RouteCandidate,
    merge_axis_contributions,
    merge_axis_difficulties,
    merge_material_values,
)

# ルート生成のステージ別サマリログ(方針は docs/logging.md)。1リクエスト=1行のINFOで
# prepare/select/trace/evaluateの所要時間と候補の減り方(折返し候補→trace成功→距離フィルタ
# 通過→上位n件)を残し、「候補が少ない/生成が遅い」の切り分けをサーバーログだけで完結できる
# ようにする。候補0件(ユーザーに何も返せない)はWARNINGへ昇格し、候補別の失敗理由はDEBUGで補足する。
logger = logging.getLogger("ridecompass.generate")

# Road Graph取得bboxの半径ヒューリスティック（目標距離に対する比率）。折返し点は往路の
# 実距離が目標の半分付近にあり、直線距離はそれより短い（実道路の迂回率は概ね1.3）ため、
# 0.5ではなく0.4から始める（0.5だとbbox面積が2.25倍になりprepare・メモリ・タイル
# キャッシュのヒット率に効く）。半径が足りない場合は一対全探索がbboxで自然に切れ、
# リング（折返し候補の集合）が欠けるだけで壊れないため、この値は経験的に調整してよい。
TURNAROUND_RADIUS_RATIO = 0.4

# 返す候補数の既定値と上限（APIの`max_routes`、api/routers/routes.py参照）。
DEFAULT_MAX_ROUTES = 8
MAX_ROUTES = 15

# 折返し点候補のプール上限: 距離フィルタや復路探索の失敗で落ちる分を見越して
# max_routesの3倍（下限12・上限40）だけ選定し、合格が`max_routes`件に達した時点で
# 早期停止する。
TURNAROUND_POOL_FACTOR = 3
TURNAROUND_POOL_MIN = 12
TURNAROUND_POOL_MAX = 40

# サーバーのローカル時刻＝Asia/Tokyoという簡易近似（Open-Meteoのhourlyもtimezone=Asia/Tokyo
# 指定でnaiveなローカル時刻文字列を返すため整合している。詳細はdocs/architecture.md参照）。
# 日本にDSTが無いことを利用して固定オフセットで表現し、追加依存（tzdata）なしで
# datetimeをtz-awareにする。
JST = timezone(timedelta(hours=9))


def turnaround_pool_size(max_routes: int) -> int:
    """`max_routes`件の合格候補を得るために選定する折返し点候補の件数。"""
    return min(TURNAROUND_POOL_MAX, max(TURNAROUND_POOL_MIN, max_routes * TURNAROUND_POOL_FACTOR))


@dataclass
class LoopTurnaround:
    """`select_loop_turnarounds`が返す折返し点候補。

    `bearing`は起点から見た折返し点の方位（表示ラベル用、候補選定には使わない）。
    `outbound_difficulty`は往路の距離加重平均difficulty（ランキング指標、0-100、
    算出不能ならNone）。`data`はエンジン固有の中間データ（復路探索に使う。往路の実距離
    [m]はエンジン固有データ側が持つ——road_graphエンジンでは`data.outbound_length_m`、
    戦略層は距離[km]を独立に持たない）。
    """

    bearing: int
    outbound_difficulty: float | None
    data: Any


@dataclass
class TracedLoop:
    """trace_loop/trace_loop_from_turnaroundの結果。距離フィルタに必要な情報と、
    evaluate_loopsが完全なRouteCandidateを組み立てるためのエンジン固有の中間データを運ぶ。

    bearing=Noneは経由地(waypoints)指定ルートを表す。周回候補と異なり「向き」という
    概念を持たず、ユーザーが指定した訪問順序をそのまま保持する必要がある
    （road_graph_engine.py: _build_best_candidateの逆回り合成をスキップする判定に使う）。
    """

    bearing: int | None
    distance_km: float
    data: Any
    # 経路上の各Edgeがどのレグ（`_RoadGraphContext.legs`の添字。周回は0=往路・1=復路、
    # 経由地ルートはレグ番号）のコスト配列で探索されたか。区間表示が探索と同じ配列から
    # 値を読むために使う。Noneは全Edgeがレグ0。
    leg_of_edge: list[int] | None = None


def candidate_identity(bearing: int | None) -> dict[str, str]:
    """方位から候補のid・方位ラベルを導出する（エンジン非依存の共通命名規則）。
    bearing=None（経由地指定ルート）は固定のid・ラベルを返す。
    周回候補のidは`generate_loops`が最終順位で`route-00..`へ振り直す（同じ方位に複数の
    候補が並びうるため、方位由来のidは一意にならない）。"""
    if bearing is None:
        return {"id": "route-waypoints", "direction_label": "経由地ルート"}
    return {"id": f"route-{bearing:03d}", "direction_label": compass_label(bearing)}


class LoopRoutingEngine(Protocol):
    engine_name: str

    async def prepare(
        self,
        origin: Coordinates,
        radius_km: float,
        waypoints: list[Coordinates] | None = None,
        now: datetime | None = None,
    ) -> Any | None: ...

    async def select_loop_turnarounds(
        self, context: Any, distance_km: float, distance_tolerance_km: float, pool_size: int
    ) -> list[LoopTurnaround]: ...

    async def trace_loop_from_turnaround(self, context: Any, turnaround: LoopTurnaround) -> TracedLoop: ...

    async def select_via_nodes(
        self, context: Any, destination: Coordinates, max_routes: int
    ) -> list[TracedLoop]: ...

    async def trace_loop(
        self,
        context: Any,
        waypoints: list[Coordinates],
        bearing: int | None,
    ) -> TracedLoop: ...

    async def evaluate_loops(
        self, context: Any, traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]: ...

    def is_loop_too_similar(self, context: Any, candidate: TracedLoop, accepted: list[TracedLoop]) -> bool: ...


class RouteGenerator:
    """周回ルート候補の生成戦略。折返し点の選定・経路計算・評価はengineへ委譲する。"""

    def __init__(self, engine: LoopRoutingEngine):
        self._engine = engine
        # candidatesが空になったときの原因（人間可読な要約、下記のlogger.warning行と
        # 同じ情報源）。呼び出し側（routes.py: _run_generate_job）が
        # RouteGenerateResponse.no_candidates_reasonへそのまま転記し、GUI（デバッグログ・
        # 候補0件時のメッセージ）から確認できるようにする。インスタンスは
        # `api/dependencies.py: _build_route_generation_setup`がリクエストごとに
        # 新規生成するため、インスタンス属性として持っても並行リクエスト間で競合しない。
        self.last_no_candidates_reason: str | None = None
        # _generate_destination_routesが目的地をアクセス可能な最寄りNodeへ補正した場合の
        # 実際の座標（補正が無ければNone）。last_no_candidates_reasonと同じ経路で
        # routes.py: _run_generate_jobがGenerationConditions.corrected_destinationへ転記する。
        self.last_destination_correction: Coordinates | None = None

    @property
    def engine_name(self) -> str:
        return self._engine.engine_name

    async def generate_loops(
        self,
        origin: Coordinates,
        distance_km: float,
        distance_tolerance_km: float,
        max_routes: int = DEFAULT_MAX_ROUTES,
        start_time: datetime | None = None,
    ) -> list[RouteCandidate]:
        radius_km = distance_km * TURNAROUND_RADIUS_RATIO
        started = time.monotonic()
        # 常時出るサマリログ用に座標を2桁(≈1km)へ丸める(debug_log.pyの方針と同じ)。
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"
        self.last_no_candidates_reason = None

        start_time = start_time or datetime.now(JST)
        context = await self._engine.prepare(origin, radius_km, now=start_time)
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

        # 折返し点候補を往路の軸的な良さの順に選定する（一対全木、エンジン側）。
        pool_size = turnaround_pool_size(max_routes)
        select_started = time.monotonic()
        turnarounds = await self._engine.select_loop_turnarounds(
            context, distance_km, distance_tolerance_km, pool_size
        )
        select_ms = round((time.monotonic() - select_started) * 1000)
        if not turnarounds:
            logger.warning(
                "generate engine=%s origin=%s target_km=%.1f -> no turnaround candidates "
                "prepare_ms=%d select_ms=%d",
                self.engine_name, origin_label, distance_km, prepare_ms, select_ms,
            )
            self.last_no_candidates_reason = (
                f"起点から片道{distance_km / 2:.1f}km前後で到達できる折返し地点が見つかりませんでした。"
                "距離や除外する道路の設定を変えてお試しください。"
            )
            return []

        # 候補はランク順に逐次処理し、距離フィルタ合格がmax_routes件に達した時点で停止する
        # （復路探索は同期・直列[road_graph_engine.py: trace_loop_from_turnaround参照]のため
        # 並列化の余地は無く、逐次ループの方が無駄な探索を省ける）。
        trace_started = time.monotonic()
        traced: list[TracedLoop] = []
        examined = 0
        failed = 0
        filtered_out = 0
        dedup_skipped = 0
        for turnaround in turnarounds:
            if len(traced) >= max_routes:
                break
            examined += 1
            try:
                loop = await self._engine.trace_loop_from_turnaround(context, turnaround)
            except RoutingError as exc:
                # 個々の候補の失敗は準正常(道路網次第で起きる)。件数はINFOサマリに含め、
                # 理由はDEBUGで補足する。全滅した場合のみ後段でWARNINGになる。
                failed += 1
                logger.debug("trace turnaround bearing=%d failed: %s", turnaround.bearing, exc)
                continue
            except Exception:  # noqa: BLE001 エンジンの不具合の可能性が高いためスタックトレース付きで残し、他候補は続行する
                failed += 1
                logger.error("trace turnaround bearing=%d unexpected error", turnaround.bearing, exc_info=True)
                continue
            if abs(loop.distance_km - distance_km) > distance_tolerance_km:
                filtered_out += 1
                logger.debug(
                    "distance filter rejected bearing=%d distance_km=%.1f (target=%.1f±%.1f)",
                    loop.bearing, loop.distance_km, distance_km, distance_tolerance_km,
                )
                continue
            # 既に採用済みの候補と周回全体（往路＋復路、進行方向無視）で重複しすぎる
            # 場合は棄却し、プールの次の折返し点候補へ進む（早期停止のn件
            # カウントもこのチェックを通過した候補数で数える、下のlen(traced)判定と同じ）。
            if traced and self._engine.is_loop_too_similar(context, loop, traced):
                dedup_skipped += 1
                continue
            traced.append(loop)
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        # 評価前に目標距離に近い順へ並べておく（最終順序はoverall_difficultyで決まるが、
        # 同点[小数1桁]の候補はこの順で並ぶ——周囲に重みを振った軸のデータが無く全候補が
        # 同じdifficultyになる場合、結果は実質的に目標距離に近い順になる。docs/tasks/T531.md）。
        traced.sort(key=lambda t: abs(t.distance_km - distance_km))

        if not traced:
            logger.warning(
                "generate engine=%s origin=%s target_km=%.1f -> no candidates "
                "(turnarounds=%d examined=%d trace_failed=%d filtered_out=%d dedup_skipped=%d) "
                "prepare_ms=%d select_ms=%d trace_ms=%d",
                self.engine_name, origin_label, distance_km,
                len(turnarounds), examined, failed, filtered_out, dedup_skipped,
                prepare_ms, select_ms, trace_ms,
            )
            self.last_no_candidates_reason = self._describe_no_traced_reason(
                distance_km, distance_tolerance_km, failed, filtered_out,
            )
            return []

        evaluate_started = time.monotonic()
        candidates = await self._engine.evaluate_loops(context, traced, start_time)
        candidates = [self._with_overall_difficulty(c) for c in candidates]
        candidates = [self._with_axis_difficulties(c) for c in candidates]
        candidates = [self._with_axis_contributions(c) for c in candidates]
        candidates = [self._with_material_values(c) for c in candidates]

        # 候補タブの並び順はoverall_difficulty（絶対基準0-100の総合難易度）昇順
        # （易しい候補が先頭）。算出不能（None）の候補は末尾へ回す。小数1桁で比較し、
        # 同点は上記の「目標距離に近い順」を安定ソートで引き継ぐ。
        candidates.sort(
            key=lambda c: round(c.overall_difficulty, 1) if c.overall_difficulty is not None else float("inf")
        )
        candidates = candidates[:max_routes]
        # 最終順位でidを振り直す（同じ方位に複数候補が並びうるため方位由来のidは一意にならない。
        # direction_labelはエンジンが方位から付けた表示用ラベルのまま）。
        candidates = [
            candidate.model_copy(update={"id": f"route-{rank:02d}"}) for rank, candidate in enumerate(candidates)
        ]
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate engine=%s origin=%s target_km=%.1f max_routes=%d -> candidates=%d "
            "turnarounds=%d examined=%d trace_failed=%d filtered_out=%d dedup_skipped=%d "
            "prepare_ms=%d select_ms=%d trace_ms=%d evaluate_ms=%d total_ms=%d",
            self.engine_name, origin_label, distance_km, max_routes, len(candidates),
            len(turnarounds), examined, failed, filtered_out, dedup_skipped,
            prepare_ms, select_ms, trace_ms, evaluate_ms, total_ms,
        )
        return candidates

    async def generate_via_waypoints(
        self,
        origin: Coordinates,
        waypoints: list[Coordinates],
        distance_km: float,
        destination: Coordinates | None = None,
        max_routes: int = 1,
        start_time: datetime | None = None,
    ) -> list[RouteCandidate]:
        """ユーザーが指定した経由地（中継地）を順に通る経路を生成する。

        `generate_loops`の折返し点選定・距離許容フィルタとは独立した経路（経由地が
        あれば、目的は「近い距離の周回」ではなく「指定した地点を通ること」自体のため）。
        `distance_km`はRoad Graph取得bboxの見積り半径にのみ使う参考値で、実際の距離は
        経由地の配置で決まる（距離フィルタは行わない）。`destination`省略時は起点に
        戻る周回（常に1件）。

        `destination`指定かつ経由地が無い（起点→目的地のみ）場合は
        `_generate_destination_routes`（via-node方式）が`max_routes`件の互いに異なる
        代替経路を返す。経由地が1つ以上ある場合はレグごとに代替案が組合せで増えるため、
        `trace_loop`による単一経路のまま（`max_routes`は無視され、`candidate_identity`
        とは別に終点到達後にid/direction_labelをroute-destination/目的地ルートへ
        上書きする）。
        """
        if destination is not None and not waypoints:
            return await self._generate_destination_routes(origin, destination, distance_km, max_routes, start_time)

        radius_km = distance_km * TURNAROUND_RADIUS_RATIO
        started = time.monotonic()
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"
        self.last_no_candidates_reason = None
        end_point = destination if destination is not None else origin
        full_waypoints = [origin, *waypoints, end_point]
        # bboxが目的地もカバーするよう、prepareへ渡す点集合に含める
        # （経由地のみのbbox計算は`_bbox_covering_points`、road_graph_engine.py参照）。
        bbox_points = [*waypoints, destination] if destination is not None else waypoints

        start_time = start_time or datetime.now(JST)
        context = await self._engine.prepare(origin, radius_km, waypoints=bbox_points, now=start_time)
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
        candidates = await self._engine.evaluate_loops(context, [traced], start_time)
        candidates = [self._with_overall_difficulty(c) for c in candidates]
        candidates = [self._with_axis_difficulties(c) for c in candidates]
        candidates = [self._with_axis_contributions(c) for c in candidates]
        candidates = [self._with_material_values(c) for c in candidates]
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

    async def _generate_destination_routes(
        self,
        origin: Coordinates,
        destination: Coordinates,
        distance_km: float,
        max_routes: int,
        start_time: datetime | None = None,
    ) -> list[RouteCandidate]:
        """経由地の無い目的地ルート（起点→目的地のみ）を、via-node方式で`max_routes`件
        まで生成する。`generate_loops`のような候補ごとの再探索・失敗
        スキップが無い（`select_via_nodes`が確定済みの経路だけを返す）ぶん、
        `generate_loops`より単純な「選定→評価」の2段階になる。
        """
        radius_km = distance_km * TURNAROUND_RADIUS_RATIO
        started = time.monotonic()
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"
        self.last_no_candidates_reason = None
        self.last_destination_correction = None

        start_time = start_time or datetime.now(JST)
        context = await self._engine.prepare(origin, radius_km, waypoints=[destination], now=start_time)
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            logger.warning(
                "generate(destination) engine=%s origin=%s max_routes=%d -> no context prepare_ms=%d",
                self.engine_name, origin_label, max_routes, prepare_ms,
            )
            self.last_no_candidates_reason = (
                f"起点{origin_label}付近の道路データが未整備のため、候補を生成できませんでした。"
                "対応エリア外の可能性があります。"
            )
            return []

        select_started = time.monotonic()
        traced = await self._engine.select_via_nodes(context, destination, max_routes)
        select_ms = round((time.monotonic() - select_started) * 1000)
        # engineが目的地をアクセス可能な最寄りNodeへ補正した場合、その座標を引き継ぐ
        # （contextはengine実装ごとに異なりうるAny型のため、無い場合はNoneのまま）。
        self.last_destination_correction = getattr(context, "destination_correction", None)
        if not traced:
            logger.warning(
                "generate(destination) engine=%s origin=%s max_routes=%d -> no via-node candidates "
                "prepare_ms=%d select_ms=%d",
                self.engine_name, origin_label, max_routes, prepare_ms, select_ms,
            )
            self.last_no_candidates_reason = (
                "指定した目的地までの経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
            )
            return []

        evaluate_started = time.monotonic()
        candidates = await self._engine.evaluate_loops(context, traced, start_time)
        candidates = [self._with_overall_difficulty(c) for c in candidates]
        candidates = [self._with_axis_difficulties(c) for c in candidates]
        candidates = [self._with_axis_contributions(c) for c in candidates]
        candidates = [self._with_material_values(c) for c in candidates]
        # generate_loopsと同じ規約: overall_difficulty昇順（算出不能はNone→末尾）。
        candidates.sort(
            key=lambda c: round(c.overall_difficulty, 1) if c.overall_difficulty is not None else float("inf")
        )
        candidates = [
            candidate.model_copy(update={"id": f"route-destination-{rank:02d}", "direction_label": "目的地ルート"})
            for rank, candidate in enumerate(candidates)
        ]
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate(destination) engine=%s origin=%s max_routes=%d -> candidates=%d "
            "prepare_ms=%d select_ms=%d evaluate_ms=%d total_ms=%d",
            self.engine_name, origin_label, max_routes, len(candidates),
            prepare_ms, select_ms, evaluate_ms, total_ms,
        )
        return candidates

    @staticmethod
    def _describe_no_traced_reason(
        distance_km: float,
        distance_tolerance_km: float,
        failed: int,
        filtered_out: int,
    ) -> str:
        """generate_loopsが`traced`空で候補0件になったときの人間可読な要約を組み立てる
        （logger.warningと同じ情報源から、RouteGenerateResponse.no_candidates_reason用に
        生成する）。"""
        parts = []
        if failed:
            parts.append(f"{failed}件の折返し候補で復路の探索に失敗しました（除外設定をご確認ください）")
        if filtered_out:
            parts.append(
                f"{filtered_out}件の周回候補は指定距離（{distance_km:.1f}km±{distance_tolerance_km:.1f}km）から外れました"
            )
        if not parts:
            # 候補プールが空でない限り到達しないはずの状態への保険。
            parts.append("周回候補が得られませんでした")
        return "、".join(parts) + "。距離や除外する道路の設定を変えてお試しください。"

    @staticmethod
    def _with_overall_difficulty(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsの区間difficultyから距離加重平均のルート単位絶対基準集約値を付与する
        （研究インターフェース改善 §10-7、エンジン非依存のためengine実装側には持たせない）。"""
        if not candidate.segments:
            return candidate
        segments = [(s.difficulty, s.distance_km) for s in candidate.segments]
        overall = distance_weighted_difficulty(segments)
        # 難易度の総量（平均×距離）も同じsegmentsから同時に付ける。並び順には使わず、
        # 「遠回りした分だけ増える」量として平均と併せて示す（domain/route.py参照）。
        return candidate.model_copy(
            update={"overall_difficulty": overall, "difficulty_load": difficulty_load(segments)}
        )

    @staticmethod
    def _with_axis_difficulties(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsのaxis_difficulties（区間ごとのaxis_id→difficulty）をルート全区間へ
        集約し、overall_difficultyと対になるルート全体版を付与する。
        既存の`merge_axis_difficulties`（domain/route.py、_merge_segment_bin用に元々あった
        もの）を候補全区間に対して1回適用するだけで得られ、新しい計算式は不要。"""
        if not candidate.segments:
            return candidate
        axis_difficulties = merge_axis_difficulties(candidate.segments)
        return candidate.model_copy(update={"axis_difficulties": axis_difficulties})

    @staticmethod
    def _with_axis_contributions(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsのaxis_contributions（区間ごとのaxis_id→重み付き寄与度）をルート
        全区間へ集約し、overall_difficultyの内訳として付与する。
        `_with_axis_difficulties`と同じ構造（`merge_axis_contributions`を候補全区間に
        1回適用するだけ）。合計は丸め誤差を除いてoverall_difficultyと一致する
        （domain/evaluation.py: compose_costs_from_axis_matrixのdocstring参照）。"""
        if not candidate.segments:
            return candidate
        axis_contributions = merge_axis_contributions(candidate.segments)
        return candidate.model_copy(update={"axis_contributions": axis_contributions})

    @staticmethod
    def _with_material_values(candidate: RouteCandidate) -> RouteCandidate:
        """segmentsのmaterial_values（区間ごとの材料id→値）をルート全区間へ集約する。
        `_with_axis_difficulties`と同じ構造。"""
        if not candidate.segments:
            return candidate
        material_values = merge_material_values(candidate.segments)
        return candidate.model_copy(update={"material_values": material_values})
