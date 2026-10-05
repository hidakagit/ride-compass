/**
 * `features/route/DifficultyProfile/DifficultyProfile.tsx`——候補の中身の先頭に出す、道のりに沿った難易度のグラフ。
 *
 * 見るもの: 長さのある区間が無ければ何も描かないこと、横軸の右端（候補の距離と渡された物差しの長い方）と目盛り、
 * 軸ごとの塗り（`axisOrder`の順に下から積む・軸の色と色の無い軸の色）、値の無い区間の灰色の塗り（総合難易度の高さ。
 * 総合難易度が無ければ塗らない）、選ばれた区間の帯とスライダーとしての値、キーボード（矢印・Home・End）と
 * 1本の指（マウス）でなぞる・押して離す操作で選ぶ区間と地点、押しただけ・ボタンを押していない動き・2本目の指が
 * 加わった操作では選ばないこと、自分で動かした地点の線（選ばれた区間の中にあるときだけ）。
 *
 * ここで見ないもの: 区間の柱と積み上げの長方形の組み方（総合難易度が0なら値の無い区間を塗らないことを含む）・
 * 区間の中の割合から地点を引く計算（道なりの形の上） →
 * `features/route/DifficultyProfile/profileGeometry.ts`。
 *
 * 差し替えたもの: グラフの実寸（`getBoundingClientRect`。テスト環境は実寸を返さない）。
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { makeRouteSegment } from "@/testing/routeFixtures";
import palette from "@/types/generated/palette.json";
import type { RouteSegmentDetail, SelectedRouteSegment } from "@/types/route";
import DifficultyProfile from "./DifficultyProfile";

// 北緯35度の上を東へ1kmずつ進む2区間（道なりの形は持たず、始点と終点を結ぶ直線の上で地点を引く）。後ろは値の無い区間。
const FIRST = makeRouteSegment({
  distance_km: 1,
  difficulty: 60,
  axis_contributions: { axis_a: 40, axis_b: 20 },
  start_latitude: 35,
  start_longitude: 139,
  end_latitude: 35,
  end_longitude: 139.01,
});
const MISSING = makeRouteSegment({
  distance_km: 1,
  difficulty: null,
  start_latitude: 35,
  start_longitude: 139.01,
  end_latitude: 35,
  end_longitude: 139.02,
});
const COLORS = { axis_a: "rgb(10, 20, 30)", axis_b: "rgb(40, 50, 60)" };

type Props = React.ComponentProps<typeof DifficultyProfile>;

function profileProps(props: Partial<Props> = {}): Props {
  return {
    segments: [FIRST, MISSING],
    overallDifficulty: 30,
    axisOrder: ["axis_a", "axis_b"],
    axisColors: COLORS,
    scaleKm: 2,
    selected: null,
    onSelect: vi.fn(),
    ...props,
  };
}

function renderProfile(props: Partial<Props> = {}) {
  const all = profileProps(props);
  const view = render(<DifficultyProfile {...all} />);
  return {
    ...view,
    onSelect: all.onSelect as ReturnType<typeof vi.fn>,
    slider: within(view.container).queryByRole("slider"),
  };
}

function selection(segment: RouteSegmentDetail): SelectedRouteSegment {
  return { segment, latitude: segment.start_latitude, longitude: segment.start_longitude };
}

/** 塗りの`path`を、塗りの色ごとに`d`で。 */
function paths(container: HTMLElement): { fill: string | null; d: string | null; opacity: string | null }[] {
  return Array.from(container.querySelectorAll("path")).map((path) => ({
    fill: path.getAttribute("fill"),
    d: path.getAttribute("d"),
    opacity: path.getAttribute("opacity"),
  }));
}

/** 地点を選んだ操作で上がった区間と、その地点の経度。 */
function lastSelection(onSelect: ReturnType<typeof vi.fn>): { segment: RouteSegmentDetail; longitude: number } {
  const [selected] = onSelect.mock.lastCall as [SelectedRouteSegment];
  expect(selected.latitude).toBeCloseTo(35, 9);
  return { segment: selected.segment, longitude: selected.longitude };
}

/** グラフの実寸を、左端100px・幅200pxにする。 */
function layOut(slider: HTMLElement) {
  vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({ left: 100, width: 200 } as DOMRect);
}

describe("DifficultyProfile", () => {
  it("長さのある区間が無ければ何も描かない", () => {
    expect(renderProfile({ segments: [] }).container).toBeEmptyDOMElement();
  });

  it("横軸の右端は、候補の距離と渡された物差しの長い方で、目盛りにその距離を出す", () => {
    const { container, unmount } = renderProfile({ scaleKm: 4 });
    expect(screen.getByText("4.0km")).toBeInTheDocument();
    // 1kmの区間が、横幅1000の4分の1を占める。
    expect(paths(container)[1].d).toBe("M0 60H250V100H0Z");
    unmount();

    renderProfile({ scaleKm: 1 });
    expect(screen.getByText("2.0km")).toBeInTheDocument();
  });

  it("区間の難易度を軸の寄与で色分けし、axisOrderの順に下から積む", () => {
    const { container } = renderProfile({ axisOrder: ["axis_a", "axis_b", "axis_c"] });
    expect(paths(container).filter((path) => path.fill !== palette.semantic.no_data)).toEqual([
      { fill: COLORS.axis_a, d: "M0 60H500V100H0Z", opacity: null },
      { fill: COLORS.axis_b, d: "M0 40H500V60H0Z", opacity: null },
    ]);
  });

  it("色の無い軸は、値の無い区間と同じ色で塗る", () => {
    const { container } = renderProfile({ segments: [FIRST], axisColors: { axis_a: COLORS.axis_a } });
    expect(paths(container).map((path) => path.fill)).toEqual([COLORS.axis_a, palette.semantic.no_data]);
  });

  it("値の無い区間は総合難易度の高さで灰色に塗り、総合難易度が無ければ塗らない", () => {
    const missingPath = (container: HTMLElement) => paths(container).find((path) => path.opacity === "0.6");
    const first = renderProfile({ overallDifficulty: 30 });
    expect(missingPath(first.container)).toEqual({
      fill: palette.semantic.no_data,
      d: "M500 70H1000V100H500Z",
      opacity: "0.6",
    });
    first.unmount();
    expect(missingPath(renderProfile({ overallDifficulty: null }).container)).toBeUndefined();
  });

  it("スライダーの値は、選ばれた区間の始まりの距離（選ばれていなければ0）", () => {
    const { slider, rerender } = renderProfile();
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", "2");
    expect(slider).toHaveAttribute("aria-valuenow", "0");
    expect(slider).toHaveAttribute("aria-valuetext", "0.0 km地点");
    expect(slider?.querySelector("rect")).toBeNull();

    rerender(<DifficultyProfile {...profileProps({ selected: selection(MISSING) })} />);
    expect(slider).toHaveAttribute("aria-valuenow", "1");
    expect(slider).toHaveAttribute("aria-valuetext", "1.0 km地点");
    expect(slider?.querySelector("rect")).toHaveAttribute("x", "500");
    expect(slider?.querySelector("rect")).toHaveAttribute("width", "500");
  });

  it("Home・Endで道のりの始点・終点を選ぶ", () => {
    const { slider, onSelect } = renderProfile();
    fireEvent.keyDown(slider!, { key: "End" });
    expect(lastSelection(onSelect)).toEqual({ segment: MISSING, longitude: 139.02 });
    fireEvent.keyDown(slider!, { key: "Home" });
    expect(lastSelection(onSelect)).toEqual({ segment: FIRST, longitude: 139 });
  });

  it("矢印は選ばれた区間の始まりから全長の1%ずつ動き、始点より手前へは出ない", () => {
    const { slider, onSelect } = renderProfile({ selected: selection(MISSING) });
    fireEvent.keyDown(slider!, { key: "ArrowRight" });
    const right = lastSelection(onSelect);
    expect(right.segment).toBe(MISSING);
    // 1km地点から0.02km進む = 2つ目の区間の2%。
    expect(right.longitude).toBeCloseTo(139.0102, 9);

    const fresh = renderProfile();
    fireEvent.keyDown(fresh.slider!, { key: "ArrowLeft" });
    expect(lastSelection(fresh.onSelect)).toEqual({ segment: FIRST, longitude: 139 });
  });

  it("選ばれた区間が短くても、帯は見える幅で描く", () => {
    const short = makeRouteSegment({ ...FIRST, distance_km: 0.001 });
    const { slider } = renderProfile({ segments: [short, MISSING], selected: selection(short) });
    expect(slider?.querySelector("rect")).toHaveAttribute("width", "2");
  });

  it("横軸が候補より長いとき、候補の終わりより右を押すと終点を選び、線も終点に引く", () => {
    const { slider, onSelect, rerender } = renderProfile({ scaleKm: 4 });
    layOut(slider!);
    // 横幅200pxのうち150px＝4kmの物差しで3km地点（候補は2kmで終わる）。
    fireEvent.pointerDown(slider!, { pointerId: 1, clientX: 250, buttons: 1 });
    fireEvent.pointerUp(slider!, { pointerId: 1, clientX: 250 });
    expect(lastSelection(onSelect)).toEqual({ segment: MISSING, longitude: 139.02 });

    rerender(<DifficultyProfile {...profileProps({ scaleKm: 4, selected: selection(MISSING) })} />);
    expect(slider?.querySelector("line")).toHaveAttribute("x1", "500");
    expect(slider).toHaveAttribute("aria-valuenow", "2");
  });

  it("矢印・Home・End以外のキーでは選ばない", () => {
    const { slider, onSelect } = renderProfile();
    fireEvent.keyDown(slider!, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("自分で動かした地点に線を引くのは、その地点が選ばれた区間の中にある間だけ", () => {
    const { slider, rerender } = renderProfile();
    fireEvent.keyDown(slider!, { key: "End" });
    // 地図で別の区間を押した。
    rerender(<DifficultyProfile {...profileProps({ selected: selection(FIRST) })} />);
    expect(slider?.querySelector("line")).toBeNull();
    expect(slider).toHaveAttribute("aria-valuenow", "0");
  });

  it("押したまま動かすとその地点を選び、離した地点も選ぶ", () => {
    const { slider, onSelect } = renderProfile();
    layOut(slider!);
    fireEvent.pointerDown(slider!, { pointerId: 1, clientX: 150, buttons: 1 });
    fireEvent.pointerMove(slider!, { pointerId: 1, clientX: 150, buttons: 1 });
    expect(lastSelection(onSelect).segment).toBe(FIRST);
    expect(lastSelection(onSelect).longitude).toBeCloseTo(139.005, 9);

    fireEvent.pointerUp(slider!, { pointerId: 1, clientX: 250 });
    expect(lastSelection(onSelect).segment).toBe(MISSING);
    expect(lastSelection(onSelect).longitude).toBeCloseTo(139.015, 9);
  });

  it("ボタンを押していない動きでは選ばない", () => {
    const { slider, onSelect } = renderProfile();
    layOut(slider!);
    fireEvent.pointerMove(slider!, { pointerId: 1, clientX: 150, buttons: 0 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("グラフの上で2本目の指が加わった操作は、全部の指が離れるまで選ばない", () => {
    const { slider, onSelect } = renderProfile();
    layOut(slider!);
    fireEvent.pointerDown(slider!, { pointerId: 1, clientX: 150, buttons: 1 });
    fireEvent.pointerDown(slider!, { pointerId: 2, clientX: 200, buttons: 1 });
    fireEvent.pointerMove(slider!, { pointerId: 1, clientX: 160, buttons: 1 });
    fireEvent.pointerUp(slider!, { pointerId: 1, clientX: 160 });
    fireEvent.pointerUp(slider!, { pointerId: 2, clientX: 200 });
    expect(onSelect).not.toHaveBeenCalled();

    // 指が全部離れたあとの1本の指の操作は、また選べる。
    fireEvent.pointerDown(slider!, { pointerId: 3, clientX: 150, buttons: 1 });
    fireEvent.pointerUp(slider!, { pointerId: 3, clientX: 150 });
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("2本目の指がグラフの外に触れても、その操作では選ばない", () => {
    const { slider, onSelect } = renderProfile();
    layOut(slider!);
    fireEvent.pointerDown(slider!, { pointerId: 1, clientX: 150, buttons: 1 });
    fireEvent.pointerDown(document.body, { pointerId: 2, buttons: 1 });
    fireEvent.pointerMove(slider!, { pointerId: 1, clientX: 160, buttons: 1 });
    fireEvent.pointerUp(slider!, { pointerId: 1, clientX: 160 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("取り消された指は数えず、そのあとの1本の指の操作で選べる", () => {
    const { slider, onSelect } = renderProfile();
    layOut(slider!);
    fireEvent.pointerDown(slider!, { pointerId: 1, clientX: 150, buttons: 1 });
    fireEvent.pointerDown(slider!, { pointerId: 2, clientX: 200, buttons: 1 });
    fireEvent.pointerCancel(slider!, { pointerId: 1 });
    fireEvent.pointerCancel(slider!, { pointerId: 2 });
    fireEvent.pointerDown(slider!, { pointerId: 3, clientX: 150, buttons: 1 });
    fireEvent.pointerUp(slider!, { pointerId: 3, clientX: 150 });
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
