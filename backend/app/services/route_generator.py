"""周回ルート生成の戦略層（エンジン非依存）。

「起点からの一対全最短経路木で目標距離の半分付近に到達する折返し点を、往路の軸的な良さの
順に選び、往路と別の復路を探索して周回にし、距離許容範囲でフィルタして、総合難易度の昇順で
上位`max_routes`件を返す」という周回生成戦略を1箇所に持つ。折返し点の選定・経路計算・
評価値の取得は`RoadGraphEngine`へ委譲する。

候補の形は公開軸の重み配分で決まる（例: 自転車インフラの重みを100%にすると、往路が
自転車インフラ上を通る折返し点ほど上位に選ばれる）。距離は目標±`distance_tolerance_km`の
厳格フィルタであり、スコアとは混ぜない。
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.domain.time_zone import JST
from app.domain.difficulty import difficulty_load, distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.loop_routing import TracedLoop

if TYPE_CHECKING:
    from app.services.road_graph_engine import RoadGraphEngine
from app.domain.route import (
    merge_axis_raw_values,
    Coordinates,
    RouteCandidate,
    merge_axis_contributions,
    merge_axis_difficulties,
    merge_material_values,
)

logger = logging.getLogger("ridecompass.generate")

# 区間を乗り換えて作ったルートのid。frontendは`route-generate-config.json`経由で
# 受け取る（一覧で生成候補と見分けるための接頭辞。両側で別々に書くと、片方だけ改名した
# ときに合成ルートが「ただの候補」として並ぶ）。
SPLICED_ROUTE_ID = "route-spliced"

# Road Graph取得bboxの半径ヒューリスティック（目標距離に対する比率）。折返し点は往路の
# 実距離が目標の半分付近にあり、直線距離は迂回率のぶんそれより短いため、0.5より小さく取る
# （比を上げるとbbox面積が二乗で効き、prepare・メモリ・タイルキャッシュのヒット率に響く）。
# 半径が足りない場合は一対全探索がbboxで自然に切れ、折返し候補が欠けるだけで壊れないため、
# この値は経験的に調整してよい。
TURNAROUND_RADIUS_RATIO = 0.4

# 返す候補数の既定値と上限（APIの`max_routes`）。
DEFAULT_MAX_ROUTES = 8
MAX_ROUTES = 15

# 折返し点候補のプール上限: 距離フィルタや復路探索の失敗で落ちる分を見越して
# max_routesの3倍（下限12・上限40）だけ選定し、合格が`max_routes`件に達した時点で
# 早期停止する。
TURNAROUND_POOL_FACTOR = 3
TURNAROUND_POOL_MIN = 12
TURNAROUND_POOL_MAX = 40


def turnaround_pool_size(max_routes: int) -> int:
    """`max_routes`件の合格候補を得るために選定する折返し点候補の件数。"""
    return min(TURNAROUND_POOL_MAX, max(TURNAROUND_POOL_MIN, max_routes * TURNAROUND_POOL_FACTOR))


#: 区間から候補単位へ集約する値（載せるフィールド → `segments`から作る関数）。
#: **集約を1段増やすときはここへ1行足す**（design-principles.md 構造仕様8）。集約は候補の
#: 並び順・印（`is_fastest`等）を読まないため、呼び出し側がそれらを付ける前でも後でも
#: 結果は変わらない。
SEGMENT_AGGREGATES: dict[str, Callable[[list[Any]], Any]] = {
    # ルート単位の絶対基準。エンジン非依存のため、engine実装側には持たせない。
    "overall_difficulty": lambda segments: distance_weighted_difficulty(
        [(s.difficulty, s.distance_km) for s in segments]),
    # 難易度の総量。並び順には使わず、「遠回りした分だけ増える」量として平均と併せて示す。
    "difficulty_load": lambda segments: difficulty_load(
        [(s.difficulty, s.distance_km) for s in segments]),
    "axis_difficulties": merge_axis_difficulties,
    # 軸単体で経路を判断するための絶対値。
    "axis_raw_values": merge_axis_raw_values,
    # overall_difficultyの内訳。合計は丸め誤差を除いてoverall_difficultyと一致する。
    "axis_contributions": merge_axis_contributions,
    # 数値材料の集約。**categorical材料の延長割合はここで触らない**——`segments`は既に
    # 約500m単位へ畳まれており、代表値からでは正しい割合を作れない（エンジンがビニングの
    # 前に計算して`RouteCandidate`へ載せている。`road_graph_engine.py: _build_candidate`）。
    "material_values": merge_material_values,
}


class RouteGenerator:
    """周回ルート候補の生成戦略。折返し点の選定・経路計算・評価はengineへ委譲する。"""

    def __init__(self, engine: "RoadGraphEngine"):
        self._engine = engine
        # 直前の生成結果に付随する情報を、戻り値とは別に置く。**インスタンスはリクエスト
        # ごとに作られる**ため、可変な属性として持っても並行リクエスト間で混ざらない。
        #: 候補が空になったときの、利用者へ見せられる理由。
        self.last_no_candidates_reason: str | None = None
        #: 目的地をアクセス可能な最寄りNodeへ補正した場合の実際の座標。
        self.last_destination_correction: Coordinates | None = None

    async def _evaluate_and_aggregate(
        self, context: Any, traced: list[TracedLoop], start_time: datetime
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

    def _explain_missing_context(
        self,
        origin_label: str,
        prepare_ms: int,
        *,
        log_label: str,
        log_detail: str,
        failure_phrase: str,
    ) -> None:
        """道路データが無くて土台を作れなかったことを、ログと利用者向けの理由に残す。

        生成の入口ごとに写経すると、文言を直したときに片方だけ古くなる。**どの入口で
        落ちたかはログのラベルが持つ**ので、ここでは骨格だけを共有する。
        """
        logger.warning(
            "%s origin=%s %s -> no context (road data unavailable) prepare_ms=%d",
            log_label, origin_label, log_detail, prepare_ms,
        )
        self.last_no_candidates_reason = (
            f"起点{origin_label}付近の道路データが未整備のため、{failure_phrase}")

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
            self._explain_missing_context(
                origin_label, prepare_ms,
                log_label="generate(loops)", log_detail=f"target_km={distance_km:.1f}",
                failure_phrase="候補を生成できませんでした。対応エリア外の可能性があります。")
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
                "generate(loops) origin=%s target_km=%.1f -> no turnaround candidates "
                "prepare_ms=%d select_ms=%d",
                origin_label, distance_km, prepare_ms, select_ms,
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
            # 採用済みの候補と周回全体（往路＋復路、進行方向は無視）で重複しすぎるものは
            # 捨て、プールの次の折返し点へ進む。
            if traced and self._engine.is_loop_too_similar(context, loop, traced):
                dedup_skipped += 1
                continue
            traced.append(loop)
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        # 評価前に目標距離に近い順へ並べておく（最終順序はoverall_difficultyで決まるが、
        # 同点[小数1桁]の候補はこの順で並ぶ——周囲に重みを振った軸のデータが無く全候補が
        # 同じdifficultyになる場合、結果は実質的に目標距離に近い順になる）。
        traced.sort(key=lambda t: abs(t.distance_km - distance_km))

        if not traced:
            logger.warning(
                "generate(loops) origin=%s target_km=%.1f -> no candidates "
                "(turnarounds=%d examined=%d trace_failed=%d filtered_out=%d dedup_skipped=%d) "
                "prepare_ms=%d select_ms=%d trace_ms=%d",
                origin_label, distance_km,
                len(turnarounds), examined, failed, filtered_out, dedup_skipped,
                prepare_ms, select_ms, trace_ms,
            )
            self.last_no_candidates_reason = self._describe_no_traced_reason(
                distance_km, distance_tolerance_km, failed, filtered_out,
            )
            return []

        evaluate_started = time.monotonic()
        candidates = await self._evaluate_and_aggregate(context, traced, start_time)

        # 候補タブの並び順はoverall_difficulty（絶対基準0-100の総合難易度）昇順
        # （易しい候補が先頭）。算出不能（None）の候補は末尾へ回す。小数1桁で比較し、
        # 同点は上記の「目標距離に近い順」を安定ソートで引き継ぐ。
        candidates.sort(
            key=lambda c: round(c.overall_difficulty, 1) if c.overall_difficulty is not None else float("inf")
        )
        # 最終順位でidを振り直す（同じ方位に複数候補が並びうるため方位由来のidは一意にならない。
        # direction_labelはエンジンが方位から付けた表示用ラベルのまま）。
        candidates = [
            candidate.model_copy(update={"id": f"route-{rank:02d}"}) for rank, candidate in enumerate(candidates)
        ]
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate(loops) origin=%s target_km=%.1f max_routes=%d -> candidates=%d "
            "turnarounds=%d examined=%d trace_failed=%d filtered_out=%d dedup_skipped=%d "
            "prepare_ms=%d select_ms=%d trace_ms=%d evaluate_ms=%d total_ms=%d",
            origin_label, distance_km, max_routes, len(candidates),
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

        `destination`指定かつ経由地が無い場合だけ、`max_routes`件の互いに異なる代替経路を
        返す。経由地が1つ以上ある場合はレグごとに代替案が組合せで増えるため単一経路のまま
        で、`max_routes`は無視される。
        """
        if destination is not None and not waypoints:
            return await self._generate_destination_routes(origin, destination, distance_km, max_routes, start_time)

        radius_km = distance_km * TURNAROUND_RADIUS_RATIO
        started = time.monotonic()
        origin_label = f"({origin.latitude:.2f},{origin.longitude:.2f})"
        self.last_no_candidates_reason = None
        end_point = destination if destination is not None else origin
        full_waypoints = [origin, *waypoints, end_point]
        # bboxが目的地もカバーするよう、prepareへ渡す点集合に含める。
        bbox_points = [*waypoints, destination] if destination is not None else waypoints

        start_time = start_time or datetime.now(JST)
        context = await self._engine.prepare(origin, radius_km, waypoints=bbox_points, now=start_time)
        prepare_ms = round((time.monotonic() - started) * 1000)
        if context is None:
            self._explain_missing_context(
                origin_label, prepare_ms, log_label="generate(via_waypoints)",
                log_detail=f"waypoints={len(waypoints)} destination={destination is not None}",
                failure_phrase="候補を生成できませんでした。対応エリア外の可能性があります。")
            return []

        trace_started = time.monotonic()
        try:
            traced = await self._engine.trace_loop(context, full_waypoints, bearing=None)
        except RoutingError as exc:
            logger.warning(
                "generate(via_waypoints) origin=%s waypoints=%d destination=%s -> trace failed: %s",
                origin_label, len(waypoints), destination is not None, exc,
            )
            self.last_no_candidates_reason = (
                "指定した経由地・目的地を通る経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
            )
            return []
        trace_ms = round((time.monotonic() - trace_started) * 1000)

        evaluate_started = time.monotonic()
        candidates = await self._evaluate_and_aggregate(context, [traced], start_time)
        if destination is not None:
            candidates = [
                c.model_copy(update={"id": "route-destination", "direction_label": "目的地ルート"})
                for c in candidates
            ]
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate(via_waypoints) origin=%s waypoints=%d destination=%s target_km=%.1f -> distance_km=%.1f "
            "prepare_ms=%d trace_ms=%d evaluate_ms=%d total_ms=%d",
            origin_label, len(waypoints), destination is not None, distance_km, traced.distance_km,
            prepare_ms, trace_ms, evaluate_ms, total_ms,
        )
        return candidates

    async def generate_spliced_route(
        self,
        origin: Coordinates,
        destination: Coordinates,
        distance_km: float,
        edge_ids: list[str],
        start_time: datetime | None = None,
    ) -> list[RouteCandidate]:
        """クライアントが区間を差し替えて組み立てた経路を、既存候補と同じ経路で評価し直す。

        探索はやり直さない（経路は確定済み）が、`prepare`は通る——評価は
        `_RoadGraphContext`のコスト配列から読むため（design-principles.md 構造仕様10:
        Edgeコストは一度だけ計算し、探索と表示が同じ値を共有する）。前半・後半の値を
        混ぜる近似にすると、その共有が壊れる。
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
            self._explain_missing_context(
                origin_label, prepare_ms, log_label="generate(spliced)",
                log_detail=f"edges={len(edge_ids)}",
                failure_phrase="ルートを組み立てられませんでした。")
            return []

        try:
            traced = self._engine.build_traced_from_edge_ids(context, edge_ids, destination)
        except RoutingError as exc:
            # 経路の形が受け取れない（空・未知のEdge・つながっていない・起点や終点が違う）。
            # **利用者へ届く理由を捨てない**——ここで素通しすると、呼び出し元の汎用catchが
            # 「ルート生成に失敗しました」に潰し、画面からは原因が分からなくなる。
            # 例外の本文は内部の識別子（node id・edge id）を含むためそのまま出さず、
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
        candidates = [
            candidate.model_copy(update={"id": SPLICED_ROUTE_ID, "direction_label": "組み合わせたルート"})
            for candidate in candidates
        ]
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        logger.info(
            "generate(spliced) origin=%s edges=%d -> distance_km=%.1f "
            "prepare_ms=%d evaluate_ms=%d total_ms=%d",
            origin_label, len(edge_ids), traced.distance_km,
            prepare_ms, evaluate_ms, round((time.monotonic() - started) * 1000),
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
        """経由地の無い目的地ルートを、via-node方式で`max_routes`件まで生成する。

        `select_via_nodes`が確定済みの経路だけを返すため、候補ごとの再探索・失敗スキップが
        無く「選定→評価」の2段で済む。

        所要時間が最短の経路を基準線として必ず1本含め、先頭へ固定する。軸の重みをすべて0に
        したときの経路であり、軸設定に沿った候補が何分余計にかかるかを対価として読める
        ようにするため。
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
            self._explain_missing_context(
                origin_label, prepare_ms, log_label="generate(destination)",
                log_detail=f"max_routes={max_routes}",
                failure_phrase="候補を生成できませんでした。対応エリア外の可能性があります。")
            return []

        select_started = time.monotonic()
        traced = await self._engine.select_via_nodes(context, destination, max_routes)
        select_ms = round((time.monotonic() - select_started) * 1000)
        # engineが目的地をアクセス可能な最寄りNodeへ補正した場合、その座標を引き継ぐ
        # （contextはengine実装ごとに異なりうるAny型のため、無い場合はNoneのまま）。
        self.last_destination_correction = getattr(context, "destination_correction", None)
        if not traced:
            side = getattr(context, "no_candidates_side", None)
            logger.warning(
                "generate(destination) origin=%s max_routes=%d -> no via-node candidates "
                "side=%s prepare_ms=%d select_ms=%d",
                origin_label, max_routes, side or "unknown", prepare_ms, select_ms,
            )
            self.last_no_candidates_reason = (
                f"起点{origin_label}から走り出せる道が見つかりませんでした。"
                "出発地を道路沿いへ動かしてお試しください。"
                if side == "origin"
                else "指定した目的地までの経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
            )
            return []

        # 距離だけで選んだ最短経路を基準線として必ず1本含める。軸設定に沿った候補と
        # 同じ経路になることもあるため、その場合は候補を増やさず既存の1本へ印を付ける。
        fastest = await self._engine.select_fastest_route(context, destination)
        fastest_index: int | None = None
        if fastest is not None:
            same = next((i for i, t in enumerate(traced) if t.data == fastest.data), None)
            if same is None:
                traced.append(fastest)
                fastest_index = len(traced) - 1
            else:
                fastest_index = same

        evaluate_started = time.monotonic()
        candidates = await self._evaluate_and_aggregate(context, traced, start_time)
        if fastest_index is not None:
            candidates[fastest_index] = candidates[fastest_index].model_copy(
                update={"is_fastest": True}
            )
        # generate_loopsと同じ規約: overall_difficulty昇順（算出不能はNone→末尾）。
        candidates.sort(
            key=lambda c: round(c.overall_difficulty, 1) if c.overall_difficulty is not None else float("inf")
        )
        # 基準線だけは難易度順の外へ出して先頭へ固定する（他の候補が何分余計にかかるかを
        # 読むための基準であり、難易度で沈むと基準として使えない）。sortは安定なため
        # 残りの難易度順は保たれる。max_routesを超えないよう末尾を切るが、先頭にいる
        # 基準線は必ず残る。
        #
        # ただし`max_routes`が1のときは固定しない。基準線は**比べる相手があって初めて
        # 基準**であり、1本だけ返すなら比べる相手が無い。固定すると返る唯一の候補が常に
        # 距離最短になり、軸の重みが結果に一切現れない（利用者から見ると「設定が効かない」）。
        if max_routes >= 2:
            candidates.sort(key=lambda c: not c.is_fastest)
        candidates = candidates[:max_routes]
        candidates = [
            candidate.model_copy(update={"id": f"route-destination-{rank:02d}", "direction_label": "目的地ルート"})
            for rank, candidate in enumerate(candidates)
        ]
        evaluate_ms = round((time.monotonic() - evaluate_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        logger.info(
            "generate(destination) origin=%s max_routes=%d -> candidates=%d "
            "prepare_ms=%d select_ms=%d evaluate_ms=%d total_ms=%d",
            origin_label, max_routes, len(candidates),
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
        """周回候補が1本も残らなかったときの、利用者へ見せる要約を組み立てる。

        折返し地点が1つ以上あって1本も残らないのは、失敗か距離外れが1件以上あるときだけ
        （1本目は似すぎを問わず、求める本数は1以上）なので、どちらも0で呼ばれることは無い。
        """
        parts = []
        if failed:
            parts.append(f"{failed}件の折返し候補で復路の探索に失敗しました（除外設定をご確認ください）")
        if filtered_out:
            parts.append(
                f"{filtered_out}件の周回候補は指定距離（{distance_km:.1f}km±{distance_tolerance_km:.1f}km）から外れました"
            )
        return "、".join(parts) + "。距離や除外する道路の設定を変えてお試しください。"
