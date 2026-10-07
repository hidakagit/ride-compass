/**
 * 「ルート結果」の状態（`useRouteResults.ts`）——生成した候補・編集で作ったルート・選んだルート・地図で押した区間・
 * 生成に使われた重みを返す。生成の結果で入れ替えると先頭を選び、編集で作ったルートは元を
 * 上書きせず作った順の番号で足して選ぶ。乗り換えで作った経路と同じ道の候補は、同じ道で選んだと分かる形で選ぶ。
 * タブを選び替える・入れ替える・消すと、押した区間を外す。
 *
 * ここで見ないもの:
 * - 候補の並び（所要時間の短い順）・一覧の見出しと名前 → `useRouteGeneration.test.ts`・`routeTabLabel.test.ts`
 * - 状態の描き方（タブ・区間の詳細・元との違い） → `RouteOutcome/RouteOutcome.test.tsx`・`EditDifference/EditDifference.test.tsx`
 * - 生成・乗り換えの結果を入れる受け渡しと、地図に描くルート → `app/page.test.tsx`
 *
 * 編集の元が一覧に無いとき（`selectedEdit.origin`がnull）は通さない: 編集は一覧にあるルートからしか作れず、一覧を
 * 入れ替える・消すと編集も一緒に消えるので、元だけが無くなる状態は作れない。
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeRouteCandidate, makeRouteSegment } from "@/testing/routeFixtures";
import type { RouteCandidate, SelectedRouteSegment } from "@/types/route";

import { useRouteResults } from "./useRouteResults";

const WEIGHTS = { axis_a: 0.3, axis_b: 0.7 };

const FIRST = makeRouteCandidate({ id: "r1", distance_km: 30 });
const SECOND = makeRouteCandidate({ id: "r2", distance_km: 32 });
// backendは合成のルートへ毎回同じidを付ける
const SPLICED = makeRouteCandidate({ id: "spliced-00", kind: "spliced", distance_km: 31 });

const SEGMENT: SelectedRouteSegment = {
  latitude: 35.6,
  longitude: 139.7,
  segment: makeRouteSegment({
    geometry: { type: "LineString", coordinates: [] },
    start_latitude: 35.6,
    start_longitude: 139.7,
    end_latitude: 35.61,
    end_longitude: 139.71,
    cumulative_distance_km: 0.5,
    distance_km: 0.5,
  }),
};

function renderResults() {
  return renderHook(() => useRouteResults());
}

type Rendered = ReturnType<typeof renderResults>;

function generated(rendered: Rendered, routes: RouteCandidate[] = [FIRST, SECOND]) {
  act(() => rendered.result.current.replaceWithGenerated(routes, WEIGHTS));
}

function pressSegment(rendered: Rendered) {
  act(() => rendered.result.current.selectSegment(SEGMENT));
  expect(rendered.result.current.selectedRouteSegment).toEqual(SEGMENT);
}

describe("生成の結果", () => {
  it("一覧を入れ替えて先頭を選び、使われた重みを持つ。編集で作ったルート・押した区間は外す", () => {
    const rendered = renderResults();
    generated(rendered);
    act(() => rendered.result.current.addEdit(SPLICED, "r1"));
    pressSegment(rendered);
    const next = makeRouteCandidate({ id: "r3" });

    act(() => rendered.result.current.replaceWithGenerated([next, FIRST], { axis_a: 1 }));

    const { result } = rendered;
    expect(result.current.routes).toEqual([next, FIRST]);
    expect(result.current.selectedCandidate).toEqual(next);
    expect(result.current.selectedRouteSegment).toBeNull();
    expect(result.current.usedWeights).toEqual({ axis_a: 1 });
  });

  it("候補0件なら何も選ばない", () => {
    const rendered = renderResults();
    generated(rendered);

    generated(rendered, []);

    expect(rendered.result.current.selectedRouteId).toBeNull();
    expect(rendered.result.current.selectedCandidate).toBeNull();
    expect(rendered.result.current.hasDetail).toBe(false);
  });
});

describe("選ぶ", () => {
  it("候補のタブへ切り替えるとそれを選び、押した区間は外す", () => {
    const rendered = renderResults();
    generated(rendered);
    act(() => rendered.result.current.selectTab("r2"));
    pressSegment(rendered);

    act(() => rendered.result.current.selectTab("r1"));
    expect(rendered.result.current.selectedCandidate).toEqual(FIRST);
    expect(rendered.result.current.selectedRouteSegment).toBeNull();
  });

  it("選んだ候補が区間の内訳を持つときだけ、区間まで確定したと返す", () => {
    const rendered = renderResults();
    generated(rendered, [FIRST, makeRouteCandidate({ id: "detailed", segments: [SEGMENT.segment] })]);
    expect(rendered.result.current.hasDetail).toBe(false);

    act(() => rendered.result.current.selectTab("detailed"));

    expect(rendered.result.current.hasDetail).toBe(true);
  });

  it("編集で作ったルートは元を上書きせず、作った順の番号のidで足して選び、押した区間を外す。使われた重みは変えない", () => {
    const rendered = renderResults();
    generated(rendered);
    pressSegment(rendered);

    act(() => rendered.result.current.addEdit(SPLICED, "r2"));

    const { result } = rendered;
    const first = { ...SPLICED, id: "spliced-1" };
    expect(result.current.routes).toEqual([FIRST, SECOND, first]);
    expect(result.current.generated).toEqual([FIRST, SECOND]);
    expect(result.current.edits).toEqual([{ route: first, originId: "r2", number: 1 }]);
    expect(result.current.selectedCandidate).toEqual(first);
    expect(result.current.selectedEdit).toEqual({ route: first, originId: "r2", number: 1, origin: SECOND });
    expect(result.current.selectedRouteSegment).toBeNull();
    expect(result.current.usedWeights).toEqual(WEIGHTS);
  });

  it("編集で作ったルートをさらに編集したものは、次の番号で足し、元はその編集。生成した候補を選び直すと編集として返さない", () => {
    const rendered = renderResults();
    generated(rendered);
    act(() => rendered.result.current.addEdit(SPLICED, "r1"));

    act(() => rendered.result.current.addEdit(SPLICED, "spliced-1"));

    const { result } = rendered;
    expect(result.current.routes.map((route) => route.id)).toEqual(["r1", "r2", "spliced-1", "spliced-2"]);
    expect(result.current.selectedEdit?.number).toBe(2);
    expect(result.current.selectedEdit?.origin?.id).toBe("spliced-1");

    act(() => result.current.selectTab("r1"));
    expect(result.current.selectedEdit).toBeNull();
  });

  it("前の描画で受け取った口で足しても、その後に足した編集・入れ替えた一覧を前へ戻さず、番号は入れ替えると1から振り直す", () => {
    const rendered = renderResults();
    generated(rendered);
    const { addEdit } = rendered.result.current;

    act(() => addEdit(SPLICED, "r1"));
    act(() => addEdit(SPLICED, "r2"));
    expect(rendered.result.current.edits.map((edit) => [edit.number, edit.originId])).toEqual([
      [1, "r1"],
      [2, "r2"],
    ]);

    generated(rendered);
    act(() => addEdit(SPLICED, "r2"));
    expect(rendered.result.current.routes.map((route) => route.id)).toEqual(["r1", "r2", "spliced-1"]);
    expect(rendered.result.current.selectedRouteId).toBe("spliced-1");
  });

  it("乗り換えで作った経路と同じ道の候補は、選んで押した区間を外し、同じ道で選んだと返す。選び直すと返さない", () => {
    const rendered = renderResults();
    generated(rendered);
    pressSegment(rendered);

    act(() => rendered.result.current.selectReused("r2"));

    const { result } = rendered;
    expect(result.current.selectedCandidate).toEqual(SECOND);
    expect(result.current.reusedRouteId).toBe("r2");
    expect(result.current.selectedRouteSegment).toBeNull();

    act(() => result.current.selectTab("r2"));
    expect(result.current.reusedRouteId).toBeNull();
  });
});

describe("消す", () => {
  it("候補・編集で作ったルート・選択・押した区間・使われた重みを消す", () => {
    const rendered = renderResults();
    generated(rendered);
    act(() => rendered.result.current.addEdit(SPLICED, "r1"));
    pressSegment(rendered);

    act(() => rendered.result.current.clear());

    const { result } = rendered;
    expect(result.current.routes).toEqual([]);
    expect(result.current.selectedRouteId).toBeNull();
    expect(result.current.selectedRouteSegment).toBeNull();
    expect(result.current.usedWeights).toBeNull();
  });
});
