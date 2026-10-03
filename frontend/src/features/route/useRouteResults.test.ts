/**
 * 「ルート結果」の状態（`useRouteResults`）——候補・編集で作ったルート・選んだ候補・地図で押した区間・比較タブ・生成に使われた重み。
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SPLICED_ROUTE_ID_PREFIX } from "@/features/route/routeTabLabel";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { RouteSegmentDetail, SelectedRouteSegment } from "@/types/route";

import { COMPARISON_TAB, useRouteResults } from "./useRouteResults";

const A = makeRouteCandidate({ id: "a" });
const B = makeRouteCandidate({ id: "b" });
const DETAILED = makeRouteCandidate({ id: "d", segments: [{} as RouteSegmentDetail] });
const SEGMENT: SelectedRouteSegment = { segment: {} as RouteSegmentDetail, latitude: 35, longitude: 139 };

function withSegmentAndComparison() {
  const hook = renderHook(() => useRouteResults());
  act(() => hook.result.current.replaceWithGenerated([A, B], { axis_a: 1 }));
  act(() => hook.result.current.selectSegment(SEGMENT));
  act(() => hook.result.current.selectTab(COMPARISON_TAB));
  return hook;
}

describe("生成の結果", () => {
  it("一覧を入れ替えて先頭を選び、使われた重みを持つ。編集で作ったルート・比較タブ・押した区間は外す", () => {
    const hook = withSegmentAndComparison();
    act(() => hook.result.current.selectSegment(SEGMENT));
    act(() => hook.result.current.addEdit(DETAILED, "a"));
    act(() => hook.result.current.replaceWithGenerated([B, A], { axis_b: 1 }));
    expect(hook.result.current).toMatchObject({
      routes: [B, A],
      edits: [],
      selectedRouteId: "b",
      selectedCandidate: B,
      comparisonTabActive: false,
      selectedRouteSegment: null,
      usedWeights: { axis_b: 1 },
    });
  });

  it("候補0件なら何も選ばない", () => {
    const hook = renderHook(() => useRouteResults());
    act(() => hook.result.current.replaceWithGenerated([], {}));
    expect(hook.result.current.selectedRouteId).toBeNull();
    expect(hook.result.current.selectedCandidate).toBeNull();
  });
});

describe("選ぶ", () => {
  it("比較タブを見ている間も選んだ候補を保ち、候補のタブへ戻るとそれを選ぶ。どちらへ切り替えても押した区間は外す", () => {
    const hook = withSegmentAndComparison();
    expect(hook.result.current.comparisonTabActive).toBe(true);
    expect(hook.result.current.selectedRouteId).toBe("a");
    expect(hook.result.current.selectedRouteSegment).toBeNull();

    act(() => hook.result.current.selectSegment(SEGMENT));
    act(() => hook.result.current.selectTab("b"));
    expect(hook.result.current).toMatchObject({
      comparisonTabActive: false,
      selectedRouteId: "b",
      selectedRouteSegment: null,
    });
  });

  it("選んだ候補が区間の内訳を持つときだけ、区間まで確定したと返す", () => {
    const hook = renderHook(() => useRouteResults());
    act(() => hook.result.current.replaceWithGenerated([A, DETAILED], {}));
    expect(hook.result.current.hasDetail).toBe(false);
    act(() => hook.result.current.selectTab("d"));
    expect(hook.result.current.hasDetail).toBe(true);
  });

  it("乗り換えで作ったルートを作った順の番号と元のidで足して選び、押した区間を外す（比較タブと使われた重みは変えない）", () => {
    const hook = withSegmentAndComparison();
    act(() => hook.result.current.selectSegment(SEGMENT));
    act(() => hook.result.current.addEdit(DETAILED, "a"));
    const first = `${SPLICED_ROUTE_ID_PREFIX}-1`;
    expect(hook.result.current).toMatchObject({
      generated: [A, B],
      edits: [{ route: { ...DETAILED, id: first }, originId: "a", number: 1 }],
      routes: [A, B, { ...DETAILED, id: first }],
      selectedRouteId: first,
      selectedEdit: { originId: "a", origin: A },
      selectedRouteSegment: null,
      comparisonTabActive: true,
      usedWeights: { axis_a: 1 },
    });

    act(() => hook.result.current.addEdit(B, first));
    expect(hook.result.current.edits.map((edit) => [edit.route.id, edit.originId, edit.number])).toEqual([
      [first, "a", 1],
      [`${SPLICED_ROUTE_ID_PREFIX}-2`, first, 2],
    ]);
  });

  it("生成したルートを選んでいる間は、編集で作ったものとして返さない", () => {
    const hook = withSegmentAndComparison();
    act(() => hook.result.current.addEdit(DETAILED, "a"));
    act(() => hook.result.current.selectTab("a"));
    expect(hook.result.current.selectedEdit).toBeNull();
  });
});

describe("消す", () => {
  it("候補・編集で作ったルート・選択・押した区間・比較タブ・使われた重みを消す", () => {
    const hook = withSegmentAndComparison();
    act(() => hook.result.current.addEdit(DETAILED, "a"));
    act(() => hook.result.current.selectSegment(SEGMENT));
    act(() => hook.result.current.clear());
    expect(hook.result.current).toMatchObject({
      routes: [],
      edits: [],
      selectedRouteId: null,
      selectedCandidate: null,
      hasDetail: false,
      selectedRouteSegment: null,
      comparisonTabActive: false,
      usedWeights: null,
    });
  });
});
