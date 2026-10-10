"""ルート生成の戦略層（エンジン非依存）。

探索して候補を作る生成は、どれも1本の骨組みを通る: 探索の土台を作る → 前段（出発地から置いた点を置いた順に、
区間ごとの最短でつなぐ）→ 仕上げの戦略で最後の固定点から先の経路を選ぶ → 評価して区間から候補単位へ集約する →
並べてラベルを付ける。仕上げの戦略は距離の有無で分かれ、どちらを使うかは要求の検証が型で選ぶ
（`domain/route_request.py: RouteTarget`）。生成の中では距離の有無を見直さない。

- 距離あり（`_DistanceFinish`）: 最後の固定点からの一対全最短経路木で、全長が目標に合う中継点（折返し点）を往路の
  軸的な良さの順に選び、それまでに走った道を避けた帰りで終点へ結び、距離許容範囲でフィルタして、総合難易度の昇順で
  上位`max_routes`件を返す。距離は目標±`distance_tolerance_km`の厳格フィルタであり、スコアとは混ぜない。
- 距離なし（`_NoDistanceFinish`）: 最後の固定点から終点へ良い道で向かう代わりの道を`max_routes`件まで出す。目的地が
  あれば所要時間が最短の1本を基準線として含める。

どちらの仕上げも、自由に選ぶ部分（最後の固定点から先）だけがそれまでに走った道を避け、置いた点どうしの区間は素直な道で
結ぶ。

候補の形は公開軸の重み配分で決まる（例: 自転車インフラの重みを100%にすると、往路が
自転車インフラ上を通る折返し点ほど上位に選ばれる）。探索・経路計算・評価値の取得は`RoadGraphEngine`へ委譲する。
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from app.domain.errors import RoutingError, SearchAreaTooLargeError
from app.domain.geo import haversine_distance_km
from app.domain.loop_routing import TracedLoop
from app.domain.route_request import FixedPoints
from app.domain.route_search import (
    by_closeness_to_target,
    difficulty_order,
    fits_loop_distance,
    keep_routes_with_baseline,
)

if TYPE_CHECKING:
    from app.services.road_graph_engine import FixedLegs, RoadGraphEngine, _RoadGraphContext
from app.domain.route import (
    Coordinates,
    RouteCandidate,
    RouteKind,
    merge_axis_contributions,
    merge_axis_difficulties,
    merge_material_values,
    merge_overall_difficulty,
)

logger = logging.getLogger("ridecompass.generate")

# Road Graph取得bboxの半径ヒューリスティック（自由に選ぶ部分の長さに対する比率）。折返し点は往路の
# 実距離が自由に選ぶ部分の半分付近にあり、直線距離は迂回率のぶんそれより短いため、0.5より小さく取る
# （比を上げるとbbox面積が二乗で効き、切り出す区間の数に比例するprepareの所要とメモリに響く）。
# 半径が足りない場合は一対全探索がbboxで自然に切れ、折返し候補が欠けるだけで壊れないため、
# この値は経験的に調整してよい。
TURNAROUND_RADIUS_RATIO = 0.4

# 折返し点候補のプール上限: 距離フィルタや復路探索の失敗で落ちる分を見越して
# max_routesの3倍（下限12・上限40）だけ選定し、合格が`max_routes`件に達した時点で
# 早期停止する。
_TURNAROUND_POOL_FACTOR = 3
_TURNAROUND_POOL_MIN = 12
_TURNAROUND_POOL_MAX = 40


def turnaround_pool_size(max_routes: int) -> int:
    """`max_routes`件の合格候補を得るために選定する折返し点候補の件数。"""
    return min(_TURNAROUND_POOL_MAX, max(_TURNAROUND_POOL_MIN, max_routes * _TURNAROUND_POOL_FACTOR))


#: 区間から候補単位へ集約する値（載せるフィールド → `segments`から作る関数）。
#: **集約を1段増やすときはここへ1行足す**（design-principles.md 構造仕様8）。集約は候補の
#: 並び順・id等を読まないため、呼び出し側がそれらを付ける前でも後でも結果は変わらない。
SEGMENT_AGGREGATES: dict[str, Callable[[list[Any]], Any]] = {
    # ルート単位の絶対基準。エンジン非依存のため、engine実装側には持たせない。
    "overall_difficulty": merge_overall_difficulty,
    "axis_difficulties": merge_axis_difficulties,
    # overall_difficultyの内訳。合計は丸め誤差を除いてoverall_difficultyと一致する。
    "axis_contributions": merge_axis_contributions,
    # 数値材料の集約。**categorical材料の延長割合はここで触らない**——`segments`は既に
    # 約500m単位へ畳まれており、代表値からでは正しい割合を作れない（エンジンがビニングの
    # 前に計算して`RouteCandidate`へ載せている。`road_graph_engine.py: _build_candidate`）。
    # 軸の生値（`axis_raw_values`）も区間が持たないため、同じくエンジンが載せる。
    "material_values": merge_material_values,
}


def _label(
    candidates: list[RouteCandidate],
    kind: RouteKind,
    name: str | None = None,
    fastest: RouteCandidate | None = None,
    *,
    spliceable: bool,
) -> list[RouteCandidate]:
    """候補へ応答のid・種類・名前・最速の印・乗り換えの可否をまとめて付ける。候補を返す経路はすべて最後にここを通る。

    idは種類と並びの位置から作り、応答の中で一意になる。`name`を渡さなければエンジンが方位から付けた名前のまま。
    最速の印は`fastest`と同じオブジェクトの1本にだけ付く。
    """
    return [
        candidate.model_copy(update={
            "id": f"{kind}-{rank:02d}",
            "kind": kind,
            "is_fastest": candidate is fastest,
            "spliceable": spliceable,
            **({"direction_label": name} if name is not None else {}),
        })
        for rank, candidate in enumerate(candidates)
    ]


#: 経由地・目的地を通る経路を結べなかったときの、利用者へ見せる理由。
_UNREACHABLE_POINTS_REASON = (
    "指定した経由地・目的地を通る経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
)


@dataclass(frozen=True)
class _Selection:
    """仕上げの戦略が選んだ経路と、評価のあとの並べ方。"""

    # 選んだ経路。空なら候補0件で、`no_candidates_reason`が利用者へ見せる理由を持つ。
    traced: list[TracedLoop]
    # 評価・集約した候補（`traced`と同じ件数・同じ順）を、応答の並びとラベルへ整える。
    arrange: Callable[[list[RouteCandidate]], list[RouteCandidate]]
    # 常時のサマリログへ載せる、戦略ごとの中間結果の減り方と所要時間。
    summary: str
    no_candidates_reason: str | None = None

    @staticmethod
    def empty(reason: str, summary: str) -> "_Selection":
        return _Selection(traced=[], arrange=lambda candidates: candidates, summary=summary, no_candidates_reason=reason)


class _Finish(Protocol):
    """仕上げの戦略。前段の最後の固定点から先の経路を選ぶ。"""

    @property
    def log_label(self) -> str: ...

    def search_radius_km(self, origin: Coordinates) -> float:
        """置いた点を覆う探索の範囲に、さらに足す半径（km）。"""
        ...

    @property
    def log_detail(self) -> str: ...

    async def select(
        self, engine: "RoadGraphEngine", context: "_RoadGraphContext", fixed: "FixedLegs",
    ) -> _Selection: ...


@dataclass(frozen=True)
class _DistanceFinish:
    """距離ありの仕上げ: 最後の固定点から中継点を往路の良さの順に選び、それまでに走った道を避けた帰りで終点
    （目的地、無ければ出発地）へ結び、全長が目標±許容に入る候補を作る。"""

    distance_km: float
    distance_tolerance_km: float
    max_routes: int
    points: FixedPoints

    @property
    def log_label(self) -> str:
        return "generate(loops)"

    def search_radius_km(self, origin: Coordinates) -> float:
        # 自由に選ぶ部分（最後の固定点 → 中継点 → 終点）の長さは、目標から前段の長さを引いた残り。前段の長さを直線で
        # 見積もるので、残りは実際より長く、範囲は広い側に倒れる。経由地が無ければ目標そのもの。
        stops = [origin, *self.points.waypoints]
        fixed_km = sum(haversine_distance_km(a, b) for a, b in zip(stops, stops[1:]))
        return max(0.0, self.distance_km - fixed_km) * TURNAROUND_RADIUS_RATIO

    @property
    def log_detail(self) -> str:
        return (
            f"target_km={self.distance_km:.1f} max_routes={self.max_routes} "
            f"waypoints={len(self.points.waypoints)} destination={self.points.destination is not None}"
        )

    async def select(self, engine: "RoadGraphEngine", context: "_RoadGraphContext", fixed: "FixedLegs") -> _Selection:
        # 中継点候補を往路の軸的な良さの順に選定する（一対全木、エンジン側）。
        pool_size = turnaround_pool_size(self.max_routes)
        select_started = time.monotonic()
        turnarounds = await engine.select_loop_turnarounds(
            context, fixed, self.points.destination, self.distance_km, self.distance_tolerance_km, pool_size
        )
        select_ms = round((time.monotonic() - select_started) * 1000)
        if not turnarounds:
            return _Selection.empty(
                f"起点から片道{self.distance_km / 2:.1f}km前後で到達できる折返し地点が見つかりませんでした。"
                "距離や除外する道路の設定を変えてお試しください。"
                if not self.points.waypoints and self.points.destination is None
                else f"置いた地点を通って全長{self.distance_km:.1f}km前後になる経路が見つかりませんでした。"
                "距離や地点、除外する道路の設定を変えてお試しください。",
                f"turnarounds=0 select_ms={select_ms}",
            )

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
            if len(traced) >= self.max_routes:
                break
            examined += 1
            try:
                loop = await engine.trace_loop_from_turnaround(context, fixed, turnaround)
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
            if not fits_loop_distance(loop.distance_km, self.distance_km, self.distance_tolerance_km):
                filtered_out += 1
                logger.debug(
                    "distance filter rejected bearing=%d distance_km=%.1f (target=%.1f±%.1f)",
                    loop.bearing, loop.distance_km, self.distance_km, self.distance_tolerance_km,
                )
                continue
            # 採用済みの候補と前段のあとの道（往路＋帰り、進行方向は無視）で重複しすぎるものは
            # 捨て、プールの次の中継点へ進む。
            if traced and engine.is_loop_too_similar(context, fixed, loop, traced):
                dedup_skipped += 1
                continue
            traced.append(loop)
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        summary = (
            f"turnarounds={len(turnarounds)} examined={examined} trace_failed={failed} "
            f"filtered_out={filtered_out} dedup_skipped={dedup_skipped} select_ms={select_ms} trace_ms={trace_ms}"
        )
        if not traced:
            return _Selection.empty(self._describe_no_traced_reason(failed, filtered_out), summary)
        return _Selection(by_closeness_to_target(traced, self.distance_km), self._arrange, summary)

    def _arrange(self, candidates: list[RouteCandidate]) -> list[RouteCandidate]:
        # 同点は評価前に付けた「目標距離に近い順」を安定ソートで引き継ぐ。周回の名前はエンジンが方位から付けたもの
        # （同じ方位に複数並びうるので、idは並びの位置から作る）。
        ordered = sorted(candidates, key=difficulty_order)
        if self.points.destination is None:
            return _label(ordered, "loop", spliceable=False)
        return _label(ordered, "destination", "目的地ルート", spliceable=True)

    def _describe_no_traced_reason(self, failed: int, filtered_out: int) -> str:
        """周回候補が1本も残らなかったときの、利用者へ見せる要約を組み立てる。

        折返し地点が1つ以上あって1本も残らないのは、失敗か距離外れが1件以上あるときだけ
        （1本目は似すぎを問わず、求める本数は1以上）なので、どちらも0で呼ばれることは無い。
        """
        parts = []
        if failed:
            parts.append(f"{failed}件の折返し候補で復路の探索に失敗しました[除外設定をご確認ください]")
        if filtered_out:
            parts.append(
                f"{filtered_out}件の周回候補は指定距離"
                f"[{self.distance_km:.1f}km±{self.distance_tolerance_km:.1f}km]から外れました"
            )
        return "、".join(parts) + "。距離や除外する道路の設定を変えてお試しください。"


@dataclass(frozen=True)
class _NoDistanceFinish:
    """距離なしの仕上げ: 前段の最後の固定点から、終点（目的地、無ければ出発地）へ良い道で向かう。

    via-node方式で互いに異なる代わりの道を最後の区間で`max_routes`件まで選ぶ。目的地があれば所要時間が最短の
    基準線を1本含める。
    """

    points: FixedPoints
    max_routes: int

    @property
    def log_label(self) -> str:
        return "generate(destination)" if self.points.destination is not None else "generate(via_waypoints)"

    def search_radius_km(self, origin: Coordinates) -> float:
        # 代わりの道は置いた点を覆う範囲（と固定の余裕）の中で探す。
        return 0.0

    @property
    def log_detail(self) -> str:
        return (
            f"waypoints={len(self.points.waypoints)} destination={self.points.destination is not None} "
            f"max_routes={self.max_routes}"
        )

    async def select(self, engine: "RoadGraphEngine", context: "_RoadGraphContext", fixed: "FixedLegs") -> _Selection:
        """`select_via_nodes`が確定済みの経路だけを返すため、候補ごとの再探索・失敗スキップが無く「選定→評価」の2段で済む。

        目的地があれば、所要時間が最短の経路を基準線として必ず1本含め（件数を切るときも残す）、最速の印を付ける。軸の重みを
        すべて0にしたときの経路であり、軸設定に沿った候補が何分余計にかかるかを対価として
        読めるようにするため。並びは周回と同じ総合難易度の昇順で、基準線も難易度の位置に並ぶ。
        """
        destination = self.points.destination
        select_started = time.monotonic()
        traced = await engine.select_via_nodes(context, fixed, destination, self.max_routes)
        select_ms = round((time.monotonic() - select_started) * 1000)
        if not traced:
            side = context.no_candidates_side
            if self.points.waypoints:
                reason = _UNREACHABLE_POINTS_REASON
            elif side == "origin":
                reason = "起点から走り出せる道が見つかりませんでした。出発地を道路沿いへ動かしてお試しください。"
            else:
                reason = "指定した目的地までの経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
            return _Selection.empty(reason, f"no via-node candidates side={side or 'unknown'} select_ms={select_ms}")
        if destination is None:
            def arrange_loops(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
                kept, _ = keep_routes_with_baseline(candidates, None, self.max_routes)
                return _label(kept, "loop", "経由地ルート", spliceable=False)

            return _Selection(traced, arrange_loops, f"select_ms={select_ms}")

        # 所要時間だけで選んだ経路を基準線として必ず1本含める。軸設定に沿った候補と
        # 同じ経路になることもあるため、その場合は候補を増やさず既存の1本へ印を付ける。
        fastest = await engine.select_fastest_route(context, fixed, destination)
        fastest_index: int | None = None
        if fastest is not None:
            same = next((i for i, t in enumerate(traced) if t.data == fastest.data), None)
            if same is None:
                traced.append(fastest)
                fastest_index = len(traced) - 1
            else:
                fastest_index = same

        def arrange(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
            # 件数を切るときに残し、印を付けるために、基準線をオブジェクトの同一性で覚えておく。
            baseline = candidates[fastest_index] if fastest_index is not None else None
            kept, baseline = keep_routes_with_baseline(candidates, baseline, self.max_routes)
            return _label(kept, "destination", "目的地ルート", fastest=baseline, spliceable=True)

        return _Selection(traced, arrange, f"select_ms={select_ms}")


class RouteGenerator:
    """ルート候補の生成。探索・経路計算・評価はengineへ委譲する。"""

    def __init__(self, engine: "RoadGraphEngine"):
        self._engine = engine
        # 直前の生成結果に付随する情報を、戻り値とは別に置く。**インスタンスはリクエスト
        # ごとに作られる**ため、可変な属性として持っても並行リクエスト間で混ざらない。
        #: 候補が空になったときの、利用者へ見せられる理由。
        self.last_no_candidates_reason: str | None = None
        #: 目的地をアクセス可能な最寄りNodeへ補正した場合の実際の座標。
        self.last_destination_correction: Coordinates | None = None

    async def _evaluate_and_aggregate(
        self, context: "_RoadGraphContext", traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]:
        """エンジンの評価を通し、区間から候補単位へ集約した完成形の`RouteCandidate`を返す。

        候補を返す経路はすべてここを通る。**集約を1段増やすときは`SEGMENT_AGGREGATES`へ
        1行足せば全経路へ同時に効く**（design-principles.md 構造仕様8）。

        `evaluate_loops`は入力`traced`と**同じ件数・同じ順**で返すこと。この層は
        `TracedLoop.data`の中身を読まないため、位置以外で突き合わせる手段が無い。件数が
        ずれると位置指定が別の候補を指し、印・ラベルが静かに入れ替わる（候補が消えるわけ
        ではないので結果だけでは気づけない）ため、ここで件数を検査する。
        """
        candidates = await self._engine.evaluate_loops(context, traced, start_time)
        if len(candidates) != len(traced):
            raise RoutingError(
                f"evaluate_loopsの戻り値が入力と対応していません traced={len(traced)} candidates={len(candidates)}"
            )
        return [
            candidate if not candidate.segments else candidate.model_copy(
                update={name: build(candidate.segments)
                        for name, build in SEGMENT_AGGREGATES.items()})
            for candidate in candidates
        ]

    async def _prepare(
        self,
        origin: Coordinates,
        points: list[Coordinates],
        radius_km: float,
        start_time: datetime,
        *,
        origin_label: str,
        log_label: str,
        log_detail: str,
        failure_phrase: str,
    ) -> "_RoadGraphContext | None":
        """探索の土台を作る。作れなければ、ログと利用者向けの理由を残してNoneを返す。

        生成の入口ごとに写経すると、文言を直したときに片方だけ古くなる。**どの入口で
        落ちたかはログのラベルが持つ**ので、ここでは骨格だけを共有する。
        """
        started = time.monotonic()
        try:
            context = await self._engine.prepare(origin, points, radius_km, now=start_time)
        except SearchAreaTooLargeError as exc:
            logger.warning(
                "%s origin=%s %s -> search area too large edges=%d limit=%d prepare_ms=%d",
                log_label, origin_label, log_detail, exc.edges, exc.limit,
                round((time.monotonic() - started) * 1000),
            )
            self.last_no_candidates_reason = (
                "探索範囲の道路が多すぎるため、ルートを生成できませんでした。"
                "距離を短くするか、経由地・目的地を起点に近づけてお試しください。")
            return None
        if context is None:
            logger.warning(
                "%s origin=%s %s -> no context (road data unavailable) prepare_ms=%d",
                log_label, origin_label, log_detail, round((time.monotonic() - started) * 1000),
            )
            self.last_no_candidates_reason = (
                f"起点付近の道路データが未整備のため、{failure_phrase}")
        return context

    async def generate_loops(
        self,
        origin: Coordinates,
        distance_km: float,
        distance_tolerance_km: float,
        max_routes: int,
        start_time: datetime,
        points: FixedPoints | None = None,
    ) -> list[RouteCandidate]:
        """距離ありの生成。置いた点（`points`。省略時は無し）の経由地を順に通り、全長が目標±許容に入る経路で目的地
        （無ければ起点）へ向かう（`_DistanceFinish`）。"""
        points = points or FixedPoints(waypoints=[], destination=None)
        return await self._generate(
            origin, points, start_time, _DistanceFinish(distance_km, distance_tolerance_km, max_routes, points),
        )

    async def generate_via_waypoints(
        self,
        origin: Coordinates,
        waypoints: list[Coordinates],
        destination: Coordinates | None,
        max_routes: int,
        start_time: datetime,
    ) -> list[RouteCandidate]:
        """距離なしの生成。置いた経由地を順に通り、目的地（省略時は起点）へ向かう（`_NoDistanceFinish`）。"""
        points = FixedPoints(waypoints=waypoints, destination=destination)
        return await self._generate(origin, points, start_time, _NoDistanceFinish(points, max_routes))

    async def _generate(
        self,
        origin: Coordinates,
        points: FixedPoints,
        start_time: datetime,
        finish: _Finish,
    ) -> list[RouteCandidate]:
        """探索の生成が通る骨組み: 土台 → 前段（置いた点を順につなぐ）→ 仕上げの戦略 → 評価と集約 → 並べてラベル。

        1回の生成を、段ごとの所要時間と戦略の中間結果の減り方を持つ1行で残す。候補が0件ならWARNINGにする。
        """
        started = time.monotonic()
        # 常時出るサマリログ用に座標を2桁(≈1km)へ丸める(debug_log.pyの方針と同じ)。
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"
        # 探索の範囲は置いた点（目的地を含む）を覆い、仕上げの戦略が自由に選ぶ部分の届く半径を足す。
        bbox_points = [*points.waypoints, *([points.destination] if points.destination is not None else [])]

        context = await self._prepare(
            origin, bbox_points, finish.search_radius_km(origin), start_time, origin_label=origin_label,
            log_label=finish.log_label, log_detail=finish.log_detail,
            failure_phrase="候補を生成できませんでした。対応エリア外の可能性があります。")
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            return []

        fixed_started = time.monotonic()
        finish_ms = 0
        try:
            fixed = await self._engine.trace_fixed_points(context, points.waypoints)
        except RoutingError as exc:
            fixed_ms = round((time.monotonic() - fixed_started) * 1000)
            selection = _Selection.empty(_UNREACHABLE_POINTS_REASON, f"fixed points failed: {exc}")
        else:
            fixed_ms = round((time.monotonic() - fixed_started) * 1000)
            finish_started = time.monotonic()
            selection = await finish.select(self._engine, context, fixed)
            finish_ms = round((time.monotonic() - finish_started) * 1000)
        # engineが目的地をアクセス可能な最寄りNodeへ補正した場合、その座標を引き継ぐ。
        self.last_destination_correction = context.destination_correction
        if not selection.traced:
            logger.warning(
                "%s origin=%s %s -> no candidates %s prepare_ms=%d fixed_ms=%d finish_ms=%d",
                finish.log_label, origin_label, finish.log_detail, selection.summary, prepare_ms, fixed_ms, finish_ms,
            )
            self.last_no_candidates_reason = selection.no_candidates_reason
            return []

        evaluate_started = time.monotonic()
        candidates = selection.arrange(await self._evaluate_and_aggregate(context, selection.traced, start_time))
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        # 候補ごとの同じ道を2度目に走る距離の割合（選んだ順。並べ直す前）。
        repeated = ",".join(f"{share:.2f}" for share in self._engine.repeated_shares(context, selection.traced))
        logger.info(
            "%s origin=%s %s -> candidates=%d %s repeated=%s "
            "prepare_ms=%d fixed_ms=%d finish_ms=%d evaluate_ms=%d total_ms=%d",
            finish.log_label, origin_label, finish.log_detail, len(candidates), selection.summary, repeated,
            prepare_ms, fixed_ms, finish_ms, evaluate_ms, round((time.monotonic() - started) * 1000),
        )
        return candidates

    async def generate_spliced_route(
        self,
        origin: Coordinates,
        destination: Coordinates,
        edge_ids: tuple[str, *tuple[str, ...]],
        start_time: datetime,
    ) -> list[RouteCandidate]:
        """クライアントが区間を差し替えて組み立てた経路を、既存候補と同じ経路で評価し直す。

        探索はやり直さない（経路は確定済み）が、`prepare`は通る——評価は
        `_RoadGraphContext`のコスト配列から読むため（design-principles.md 構造仕様10:
        Edgeコストは一度だけ計算し、探索と表示が同じ値を共有する）。前半・後半の値を
        混ぜる近似にすると、その共有が壊れる。
        """
        started = time.monotonic()
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"

        context = await self._prepare(
            origin, [destination], 0.0, start_time, origin_label=origin_label,
            log_label="generate(spliced)", log_detail=f"edges={len(edge_ids)}",
            failure_phrase="ルートを組み立てられませんでした。")
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            return []

        try:
            traced = self._engine.build_traced_from_edge_ids(context, edge_ids, destination)
        except RoutingError as exc:
            # 経路の形が受け取れない（未知のEdge・つながっていない・起点や終点が違う）。
            # **利用者へ届く理由を捨てない**——ここで素通しすると、呼び出し元の汎用catchが
            # 「ルート生成に失敗しました」に潰し、画面からは原因が分からなくなる。
            # 例外の本文は内部の言葉（Edgeの件数・ノードの地点）で書かれているためそのまま出さず、
            # ログにだけ残して利用者には何が起きたかだけを伝える。
            logger.warning(
                "generate(spliced) origin=%s edges=%d -> 経路の形が受け取れない: %s",
                origin_label, len(edge_ids), exc,
            )
            self.last_no_candidates_reason = (
                "組み合わせた経路がつながっていないため評価できませんでした。"
                "区間の選び直しか、ルートの再生成をお試しください。"
            )
            return []

        evaluate_started = time.monotonic()
        candidates = await self._evaluate_and_aggregate(context, [traced], start_time)
        candidates = _label(candidates, "spliced", "組み合わせたルート", spliceable=True)
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        logger.info(
            "generate(spliced) origin=%s edges=%d -> distance_km=%.1f "
            "prepare_ms=%d evaluate_ms=%d total_ms=%d",
            origin_label, len(edge_ids), traced.distance_km,
            prepare_ms, evaluate_ms, round((time.monotonic() - started) * 1000),
        )
        return candidates
