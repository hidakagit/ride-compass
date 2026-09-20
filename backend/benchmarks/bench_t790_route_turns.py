"""改善計画T790段階3: 本番のエンジンが実際に返す経路のターンを数える。

`RouteGenerator.generate_via_waypoints`（目的地ルート）を本番と同じ経路で呼び、返ってきた
候補の右左折・Uターン・上位の道との交差の回数を数える。ターンの費用が実際の候補へ効いて
いるかを、探索の内部ではなく**出てきた経路**で確かめるためのもの。

実DB接続が必須。読み取り経路のみを通す（bench_t790_turn_expandedと同じガード）。

使い方: `python -m benchmarks.bench_t790_route_turns`
（起点・目的地は`T790_ORIGIN`/`T790_DESTINATION`で上書きできる）
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from app.domain.routing import TurnCostSpec, current_turn_cost
from app.domain.traffic import highway_rank
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session
from benchmarks._revision import announce_revision


def _coordinate_from_env(name: str, default: Coordinates) -> Coordinates:
    raw = os.environ.get(name)
    if not raw:
        return default
    latitude, longitude = (float(part) for part in raw.split(","))
    return Coordinates(latitude=latitude, longitude=longitude)


# 実走で報告された区間（柏→王子）。
ORIGIN = _coordinate_from_env("T790_ORIGIN", Coordinates(latitude=35.8617, longitude=139.9707))
DESTINATION = _coordinate_from_env("T790_DESTINATION", Coordinates(latitude=35.7528, longitude=139.7386))
DISTANCE_KM = float(os.environ.get("T790_DISTANCE_KM", "30"))
MAX_ROUTES = int(os.environ.get("T790_MAX_ROUTES", "3"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("ridecompass.graph").setLevel(logging.INFO)


def _node_max_rank(graph: RoadGraphLike) -> dict[str, int]:
    """Nodeごとに、そこへ集まる道の最大階級。"""
    ranks: dict[str, int] = {}
    for edge in graph.edges.values():
        rank = highway_rank(edge.highway)
        for node_id in (edge.from_node_id, edge.to_node_id):
            if rank > ranks.get(node_id, 0):
                ranks[node_id] = rank
    return ranks


def _count_turns(graph: RoadGraphLike, edge_ids: list[str], spec: TurnCostSpec) -> dict[str, int]:
    """経路上のターンを数える。`major_crossing`は「自分より上位の道と交わる交差点を通った
    回数」で、そのうち曲がったものが`major_turn`。"""
    counts = {"left": 0, "right": 0, "uturn": 0, "major_crossing": 0, "major_turn": 0}
    node_rank = _node_max_rank(graph)
    for previous_id, next_id in zip(edge_ids, edge_ids[1:]):
        previous = graph.edges.get(previous_id)
        following = graph.edges.get(next_id)
        if previous is None or following is None or previous.bearing_deg is None or following.bearing_deg is None:
            continue
        delta = (following.bearing_deg - previous.bearing_deg + 180.0) % 360.0 - 180.0
        is_uturn = following.to_node_id == previous.from_node_id
        straight = abs(delta) <= spec.straight_max_deg
        if is_uturn:
            counts["uturn"] += 1
        elif not straight:
            counts["left" if delta < 0 else "right"] += 1
        if not is_uturn and node_rank.get(previous.to_node_id, 0) > highway_rank(previous.highway):
            counts["major_crossing"] += 1
            if not straight:
                counts["major_turn"] += 1
    return counts


async def main() -> None:
    print(f"origin={ORIGIN} destination={DESTINATION} max_routes={MAX_ROUTES} (T790段階3)")
    await refresh_axis_registry()
    # ターンの費用の有無で同じ条件を比べる（費用ゼロが従来の挙動）。
    variants = {
        "ターン費用なし（従来）": TurnCostSpec(
            left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0,
            major_crossing_seconds=0.0, major_turn_seconds=0.0,
        ),
        "ターン費用あり（現行）": current_turn_cost(),
    }
    # 1回目は材料のDB読み出し（冷パス）が支配的で比較にならないため、捨てる1回を先に回す。
    async with route_generator_session(RoutePreference()) as warmup:
        started = time.monotonic()
        await warmup.generate_via_waypoints(
            ORIGIN, [], DISTANCE_KM, destination=DESTINATION, max_routes=MAX_ROUTES
        )
        print(f"[ウォームアップ] total_wall_ms={round((time.monotonic() - started) * 1000)}")

    for label, spec in variants.items():
        async with route_generator_session(RoutePreference(), turn_cost=spec) as generator:
            started = time.monotonic()
            candidates = await generator.generate_via_waypoints(
                ORIGIN, [], DISTANCE_KM, destination=DESTINATION, max_routes=MAX_ROUTES
            )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            print(f"[{label}] 候補={len(candidates)}件 total_wall_ms={elapsed_ms}")
            if not candidates:
                print("  候補0件:", generator.last_no_candidates_reason)
                continue
            context = await generator._engine.prepare(ORIGIN, DISTANCE_KM, waypoints=[DESTINATION])
            for candidate in candidates:
                counts = _count_turns(context.graph, list(candidate.edge_ids), current_turn_cost())
                turns = counts["left"] + counts["right"]
                print(
                    f"  {candidate.distance_km:.1f}km 区間{len(candidate.edge_ids)}本 "
                    f"左折{counts['left']} 右折{counts['right']} 計{turns} Uターン{counts['uturn']} "
                    f"上位道路との交差{counts['major_crossing']}（うち曲がる{counts['major_turn']}）"
                )


if __name__ == "__main__":
    announce_revision()
    asyncio.run(main())
