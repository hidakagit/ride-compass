import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RouteCandidate } from "@/types/route";
import type { ExperimentSlot } from "@/types/experimentSlot";
import ComparisonPanel from "./ComparisonPanel";

function makeCandidate(overrides: Partial<RouteCandidate>): RouteCandidate {
  return {
    id: "route-1",
    direction_label: "北",
    distance_km: 30,
    geometry: { type: "LineString", coordinates: [] },
    elevation_gain_m: null,
    min_elevation_m: null,
    max_elevation_m: null,
    max_gradient_percent: null,
    wind_score: null,
    road_score: null,
    total_score: 88,
    score_breakdown: null,
    segments: null,
    overall_difficulty: null,
    ...overrides,
  };
}

function makeSlot(overrides: Partial<ExperimentSlot>): ExperimentSlot {
  return {
    id: "slot-1",
    color: "#16a34a",
    engine: "road_graph",
    conditions: {
      latitude: 35.0,
      longitude: 139.0,
      distance_km: 30,
      distance_tolerance_km: 5,
      scoring_weights: { distance_weight: 0.3, elevation_weight: 0.15, wind_weight: 0.3, road_weight: 0.25 },
      route_preference: { elevation_weight: 0.25, road_weight: 0.3, wind_weight: 0.45 },
      generated_at: "2026-08-15T12:00:00+09:00",
    },
    topCandidate: makeCandidate({ overall_difficulty: 42.3 }),
    ...overrides,
  };
}

describe("ComparisonPanel", () => {
  it("スロットが1件以下のときは何も表示しない", () => {
    const { container } = render(<ComparisonPanel slots={[makeSlot({})]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("スロットが2件以上のとき、生値と絶対難易度の比較表を表示する", () => {
    const slots = [
      makeSlot({ id: "a", topCandidate: makeCandidate({ distance_km: 30.1, overall_difficulty: 40 }) }),
      makeSlot({ id: "b", topCandidate: makeCandidate({ distance_km: 29.8, overall_difficulty: 55 }) }),
    ];
    render(<ComparisonPanel slots={slots} />);

    expect(screen.getByText(/30\.1 km/)).toBeInTheDocument();
    expect(screen.getByText(/29\.8 km/)).toBeInTheDocument();
    expect(screen.getByText("40.0")).toBeInTheDocument();
    expect(screen.getByText("55.0")).toBeInTheDocument();
  });

  it("total_scoreは表(表示テキスト)に含めない(スロット間比較の誤用防止)", () => {
    const slots = [
      makeSlot({ id: "a", topCandidate: makeCandidate({ total_score: 12.3 }) }),
      makeSlot({ id: "b", topCandidate: makeCandidate({ total_score: 45.6 }) }),
    ];
    render(<ComparisonPanel slots={slots} />);

    expect(screen.queryByText(/12\.3/)).not.toBeInTheDocument();
    expect(screen.queryByText(/45\.6/)).not.toBeInTheDocument();
  });
});
