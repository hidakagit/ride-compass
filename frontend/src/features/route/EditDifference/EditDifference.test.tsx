/**
 * 「元との違い」（`EditDifference`）——元の名前と距離・変えた区間の数、指標の差、変えた区間ごとの長さの差を出し、
 * 「元を見る」で元へ切り替える操作を上げる。差の求め方は`routeEditDiff.ts`のテストが見る。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeRouteCandidate } from "@/testing/routeFixtures";

import EditDifference from "./EditDifference";

const line = (points: [number, number][]) => ({ type: "LineString" as const, coordinates: points });
const ORIGIN = makeRouteCandidate({
  distance_km: 16,
  estimated_duration_seconds: 3000,
  overall_difficulty: { average: 35, load: 6 },
  edge_ids: ["e1", "a1", "e2"],
  edge_point_offsets: [0, 1, 2, 3],
  geometry: line([
    [0, 0],
    [0.01, 0],
    [0.02, 0],
    [0.03, 0],
  ]),
});
const EDITED = makeRouteCandidate({
  distance_km: 15.6,
  estimated_duration_seconds: 2880,
  overall_difficulty: { average: 30, load: 5 },
  edge_ids: ["e1", "b1", "e2"],
  edge_point_offsets: [0, 1, 3, 4],
  geometry: line([
    [0, 0],
    [0.01, 0],
    [0.015, 0.005],
    [0.02, 0],
    [0.03, 0],
  ]),
});

describe("EditDifference", () => {
  it("元の名前と距離・変えた区間の数、指標の差、変えた区間の元の位置と長さの差を出す", () => {
    render(<EditDifference originName="2" origin={ORIGIN} edited={EDITED} onShowOrigin={vi.fn()} />);
    const section = screen.getByRole("region", { name: "元との違い" });
    expect(section).toHaveTextContent("元: 2 16.0km から1区間");
    const values = within(section)
      .getAllByRole("definition")
      .map((item) => item.textContent);
    expect(values).toEqual(["−0.4km", "−2分", "−5", "−1"]);
    expect(within(section).getByRole("listitem")).toHaveTextContent("1.1〜2.2km+0.5km");
  });

  it("値を持たない指標は「—」にする", () => {
    render(
      <EditDifference
        originName="2"
        origin={{ ...ORIGIN, overall_difficulty: null }}
        edited={EDITED}
        onShowOrigin={vi.fn()}
      />,
    );
    const values = screen.getAllByRole("definition").map((item) => item.textContent);
    expect(values.slice(2)).toEqual(["—", "—"]);
  });

  it("「元を見る」で元へ切り替える操作を上げる", async () => {
    const user = userEvent.setup();
    const onShowOrigin = vi.fn();
    render(<EditDifference originName="2" origin={ORIGIN} edited={EDITED} onShowOrigin={onShowOrigin} />);
    await user.click(screen.getByRole("button", { name: "元を見る" }));
    expect(onShowOrigin).toHaveBeenCalledTimes(1);
  });
});
