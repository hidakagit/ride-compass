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

  // 改善計画T331: 選択状態スタイル・条件付き表示4項目（おすすめ度・獲得標高・風・舗装率）の
  // 肯定的な検証が無かったため追加。
  describe("選択状態スタイル・条件付き表示（改善計画T331）", () => {
    it("選択中の候補はitemSelectedクラスを持ち、非選択の候補は持たない", () => {
      const routes = [makeRoute({ id: "a" }), makeRoute({ id: "b" })];
      render(<RouteList routes={routes} selectedRouteId="a" onSelect={vi.fn()} />);

      const [buttonA, buttonB] = screen.getAllByRole("button");
      expect(buttonA.className).toMatch(/itemSelected/);
      expect(buttonB.className).not.toMatch(/itemSelected/);
    });

    it("total_scoreが指定されていればおすすめ度を表示し、nullなら表示しない", () => {
      const routes = [
        makeRoute({ id: "a", total_score: 87.6 }),
        makeRoute({ id: "b", total_score: null }),
      ];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(screen.getByText(/おすすめ度 88点/)).toBeInTheDocument();
      const buttons = screen.getAllByRole("button");
      expect(buttons[1].textContent).not.toMatch(/おすすめ度/);
    });

    it("elevation_gain_mが指定されていれば獲得標高を表示し、nullなら表示しない", () => {
      const routes = [
        makeRoute({ id: "a", elevation_gain_m: 123.4 }),
        makeRoute({ id: "b", elevation_gain_m: null }),
      ];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(screen.getByText(/獲得標高 123 m/)).toBeInTheDocument();
      const buttons = screen.getAllByRole("button");
      expect(buttons[1].textContent).not.toMatch(/獲得標高/);
    });

    it("wind_scoreが正の値なら向かい風、負の値なら追い風として絶対値を表示する", () => {
      const routes = [
        makeRoute({ id: "a", wind_score: 3.2 }),
        makeRoute({ id: "b", wind_score: -2.5 }),
      ];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(screen.getByText(/向かい風 3\.2 m\/s/)).toBeInTheDocument();
      expect(screen.getByText(/追い風 2\.5 m\/s/)).toBeInTheDocument();
    });

    it("wind_scoreがnullなら風の表示自体を出さない", () => {
      const routes = [makeRoute({ id: "a", wind_score: null })];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      // ページ先頭のおすすめ度説明文（scoreHint）自体が「向かい風」という語を含むため、
      // 判定は候補行のボタン本文だけに絞る。
      expect(screen.getByRole("button").textContent).not.toMatch(/向かい風|追い風/);
    });

    it("road_scoreが指定されていれば舗装率を表示し、nullなら表示しない", () => {
      const routes = [
        makeRoute({ id: "a", road_score: 76.4 }),
        makeRoute({ id: "b", road_score: null }),
      ];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(screen.getByText(/舗装率 76%/)).toBeInTheDocument();
      const buttons = screen.getAllByRole("button");
      expect(buttons[1].textContent).not.toMatch(/舗装率/);
    });
  });
});
