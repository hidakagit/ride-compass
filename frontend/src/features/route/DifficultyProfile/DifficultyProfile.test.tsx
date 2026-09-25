import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RouteSegmentDetail } from "@/types/route";

import DifficultyProfile from "./DifficultyProfile";

function segment(distanceKm: number, startLng: number, difficulty: number | null): RouteSegmentDetail {
  return {
    geometry: null,
    start_latitude: 35,
    start_longitude: startLng,
    end_latitude: 35,
    end_longitude: startLng + 0.01,
    cumulative_distance_km: 0,
    distance_km: distanceKm,
    difficulty,
    axis_contributions: difficulty === null ? {} : { a: difficulty },
  } as RouteSegmentDetail;
}

const SEGMENTS = [segment(1, 139, 20), segment(3, 139.01, 60)];

function renderProfile(onSelect = vi.fn(), scaleKm = 4) {
  render(
    <DifficultyProfile
      segments={SEGMENTS}
      overallDifficulty={50}
      axisOrder={["a"]}
      axisColors={{ a: "#123456" }}
      scaleKm={scaleKm}
      selected={null}
      onSelect={onSelect}
    />,
  );
  const slider = screen.getByRole("slider");
  // 描画の幅を400pxとして、押した位置を距離へ直す（jsdomは幅を持たない）。
  slider.getBoundingClientRect = () => ({ left: 0, width: 400, top: 0, height: 56, right: 400, bottom: 56 }) as DOMRect;
  return { slider, onSelect };
}

describe("道のりに沿った難易度の操作", () => {
  it("押した位置の距離の区間と、その区間の道なりの地点を選ぶ", () => {
    const { slider, onSelect } = renderProfile();

    // 4kmを400pxで描く。250px＝2.5kmは2本目（1〜4km）の半分の地点。
    fireEvent.pointerDown(slider, { clientX: 250, buttons: 1, pointerId: 1 });

    const selection = onSelect.mock.calls.at(-1)?.[0];
    expect(selection.segment).toBe(SEGMENTS[1]);
    expect(selection.longitude).toBeCloseTo(139.015, 6);
    expect(selection.latitude).toBeCloseTo(35, 6);
  });

  it("押したまま動かすと選び直し、押していない移動では選ばない", () => {
    const { slider, onSelect } = renderProfile();
    fireEvent.pointerMove(slider, { clientX: 50, buttons: 0 });
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.pointerDown(slider, { clientX: 50, buttons: 1, pointerId: 1 });
    fireEvent.pointerMove(slider, { clientX: 350, buttons: 1 });
    expect(onSelect.mock.calls.map(([selection]) => selection.segment)).toEqual([SEGMENTS[0], SEGMENTS[1]]);
  });

  it("横軸が候補より長いとき、候補の終わりより右を押すと終点を選ぶ", () => {
    const { slider, onSelect } = renderProfile(vi.fn(), 8);
    fireEvent.pointerDown(slider, { clientX: 390, buttons: 1, pointerId: 1 });
    const selection = onSelect.mock.calls.at(-1)?.[0];
    expect(selection.segment).toBe(SEGMENTS[1]);
    expect(selection.longitude).toBeCloseTo(139.02, 6);
  });

  it("キーボードでも地点を動かせる（終点・始点へ飛べる）", () => {
    const { slider, onSelect } = renderProfile();
    fireEvent.keyDown(slider, { key: "End" });
    expect(onSelect.mock.calls.at(-1)?.[0].longitude).toBeCloseTo(139.02, 6);
    fireEvent.keyDown(slider, { key: "Home" });
    expect(onSelect.mock.calls.at(-1)?.[0].segment).toBe(SEGMENTS[0]);
  });
});
