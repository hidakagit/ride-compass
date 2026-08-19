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
    stop_density: null,
    car_stress_score: null,
    bicycle_infra_score: null,
    intersection_density: null,
    accident_density: null,
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
      route_preference: {
        elevation_weight: 0.15, road_weight: 0.19, wind_weight: 0.26, stop_weight: 0.2,
        car_stress_weight: 0.2, accident_weight: 0.08,
        night_weight: 0.0,
      },
      car_stress_recipe: {
        lanes_low_threshold: 1, lanes_low_adjustment: -1,
      },
      road_suitability_recipe: {
        base_by_highway: { residential: 2 },
        cycleway_track_adjustment: -2, cycleway_lane_adjustment: -1, cycleway_shared_adjustment: -1,
      },
      motor_vehicle_density_recipe: {
        maxspeed_low_threshold: 30, maxspeed_low_adjustment: -1,
        maxspeed_high_threshold: 60, maxspeed_high_adjustment: 1,
        lanes_high_threshold: 4, lanes_high_adjustment: 1,
        designation_adjustment: 1,
      },
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

  it("停止密度の行を表示する(改善計画T45、静的属性P1で追加された軸)", () => {
    const slots = [
      makeSlot({ id: "a", topCandidate: makeCandidate({ stop_density: 1.5 }) }),
      makeSlot({ id: "b", topCandidate: makeCandidate({ stop_density: null }) }),
    ];
    render(<ComparisonPanel slots={slots} />);

    expect(screen.getByText("停止密度")).toBeInTheDocument();
    expect(screen.getByText("1.50 回/km")).toBeInTheDocument();
  });

  it("車ストレス・自転車インフラ率・交差点密度の行を表示する(静的属性P1残り、設計レビュー再発分の修正)", () => {
    const slots = [
      makeSlot({
        id: "a",
        topCandidate: makeCandidate({ car_stress_score: 2.3, bicycle_infra_score: 12.4, intersection_density: 3.1 }),
      }),
      makeSlot({ id: "b", topCandidate: makeCandidate({}) }),
    ];
    render(<ComparisonPanel slots={slots} />);

    expect(screen.getByText("車の圧迫感")).toBeInTheDocument();
    expect(screen.getByText("2.3")).toBeInTheDocument();
    expect(screen.getByText("自転車インフラ率")).toBeInTheDocument();
    expect(screen.getByText("12%")).toBeInTheDocument();
    expect(screen.getByText("交差点密度")).toBeInTheDocument();
    expect(screen.getByText("3.10 回/km")).toBeInTheDocument();
  });

  it("事故密度の行を表示する(外部静的データソース T50残作業、8軸目)", () => {
    const slots = [
      makeSlot({ id: "a", topCandidate: makeCandidate({ accident_density: 0.15 }) }),
      makeSlot({ id: "b", topCandidate: makeCandidate({}) }),
    ];
    render(<ComparisonPanel slots={slots} />);

    expect(screen.getByText("事故密度")).toBeInTheDocument();
    expect(screen.getByText("0.15 件/(km・年)")).toBeInTheDocument();
  });

  it("重みの表示(title属性)に評価軸カタログの全軸が含まれる(改善計画T45)", () => {
    // 以前はformatWeightsが3軸を手作業で列挙しており、静的属性P1で追加された
    // stop_weightが実験条件の表示から漏れていた(研究モードでstop_weightを変えて
    // 比較しても条件表示に差が現れない実害)。カタログ生成後は全軸が含まれる。
    const slots = [makeSlot({ id: "a" }), makeSlot({ id: "b" })];
    render(<ComparisonPanel slots={slots} />);

    const headers = screen.getAllByRole("columnheader").filter((el) => el.hasAttribute("title"));
    expect(headers).toHaveLength(2);
    for (const header of headers) {
      const title = header.getAttribute("title") ?? "";
      // ラベルは地図の見え方パネルと同じ軸カタログ由来の正式名称（改善計画: 研究タブを
      // 地図表示・地図の見え方パネルと考え方を併せて再設計）。以前は独自の言い換え
      // 「信号・踏切等」だったが、地図の「停止密度」へ統一した。
      expect(title).toContain("停止密度");
      expect(title).toContain("score");
      expect(title).toContain("pref");
    }
  });
});
