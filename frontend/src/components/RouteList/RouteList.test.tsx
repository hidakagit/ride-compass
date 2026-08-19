import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import RouteList from "./RouteList";

function makeRoute(overrides: Partial<RouteCandidate>): RouteCandidate {
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
    stop_density: null,
    car_stress_score: null,
    bicycle_infra_score: null,
    intersection_density: null,
    accident_density: null,
    total_score: null,
    score_breakdown: null,
    segments: null,
    overall_difficulty: null,
    ...overrides,
  };
}

describe("RouteList", () => {
  it("候補が無い場合は何も表示しない", () => {
    const { container } = render(<RouteList routes={[]} selectedRouteId={null} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("各候補の距離と方向を表示し、選択中の候補をボタンで示す", () => {
    const routes = [makeRoute({ id: "a", direction_label: "北", distance_km: 30.2 }), makeRoute({ id: "b", direction_label: "南", distance_km: 28.5 })];
    render(<RouteList routes={routes} selectedRouteId="a" onSelect={vi.fn()} />);

    expect(screen.getByText(/北方向/)).toBeInTheDocument();
    expect(screen.getByText(/南方向/)).toBeInTheDocument();
    expect(screen.getByText(/30\.2 km/)).toBeInTheDocument();
  });

  it("候補をクリックするとonSelectがそのidで呼ばれる", async () => {
    const user = userEvent.setup();
    const routes = [makeRoute({ id: "a" }), makeRoute({ id: "b" })];
    const onSelect = vi.fn();
    render(<RouteList routes={routes} selectedRouteId="a" onSelect={onSelect} />);

    await user.click(screen.getAllByRole("button")[1]);

    expect(onSelect).toHaveBeenCalledWith("b");
  });
});
