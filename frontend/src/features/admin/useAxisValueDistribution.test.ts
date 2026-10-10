/**
 * 軸スタジオの生値分布の取得（`features/admin/useAxisValueDistribution.ts: useAxisValueDistribution`）——分布の形を決める鍵が落ち着いてから取りに行き、
 * 取り直している間は前の分布を出したまま取得中を示し、失敗を文言で返す。
 *
 * ここで見ないもの:
 * - 分布を描く・各階級の点数 → `AxisStudio/`の部品と`useScoresPreview.ts`
 * - 鍵（`termsKey`）の組み立て → 呼び出し元の部品
 * - 間引きの待ち方そのもの → `hooks/useDebouncedValue.ts`（ここでは本物を通し、時計を進める）
 *
 * 差し替えたもの: 分布の応答（網の層）。送った形ごとに決まった分布を返す。
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ValueDistribution } from "@/features/admin/AxisStudio/scoreDistribution";
import { MAP_FETCH_DEBOUNCE_MS } from "@/hooks/useDebouncedValue";
import { heldReplies, onSameOrigin } from "@/testing/backendServer";
import type { AxisShape } from "@/types/route";

import { useAxisValueDistribution } from "./useAxisValueDistribution";

const shape = (materialId: string) =>
  ({ kind: "linear", terms: [{ material_id: materialId, weight: 1 }] }) as unknown as AxisShape;
const SHAPE_A = shape("num_a");
const SHAPE_B = shape("num_b");
const SHAPE_C = shape("num_c");
const DIST_A = { edges: [0, 1], counts: [3] } as unknown as ValueDistribution;
const DIST_B = { edges: [0, 2], counts: [5] } as unknown as ValueDistribution;
const DIST_C = { edges: [0, 3], counts: [7] } as unknown as ValueDistribution;
const DISTRIBUTIONS = new Map([
  [JSON.stringify(SHAPE_A), DIST_A],
  [JSON.stringify(SHAPE_B), DIST_B],
  [JSON.stringify(SHAPE_C), DIST_C],
]);

const PREVIEW = "/admin/api/axis-definitions/preview-distribution";

/** 送った形の分布を返す。 */
function serveDistributions() {
  onSameOrigin("POST", PREVIEW, ({ body }) =>
    Response.json(DISTRIBUTIONS.get(JSON.stringify((body as { shape: AxisShape }).shape))),
  );
}

interface Args {
  termsKey: string;
  shape: AxisShape;
}

function mount(initial: Args) {
  return renderHook(({ termsKey, shape }: Args) => useAxisValueDistribution(termsKey, () => shape), {
    initialProps: initial,
  });
}

/** 時計を進め、取得の結果が届くまでの区切りも流す。 */
async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("取りに行かないとき", () => {
  it("鍵が空なら、分布も取得中も失敗も無く、問い合わせない", async () => {
    const { result } = mount({ termsKey: "", shape: SHAPE_A });
    await advance(MAP_FETCH_DEBOUNCE_MS);

    expect(result.current).toEqual({ distribution: null, loading: false, error: null });
  });

  it("取れた後に鍵が空へ変わると、分布を出さない", async () => {
    serveDistributions();
    const { result, rerender } = mount({ termsKey: "k1", shape: SHAPE_A });
    await advance();
    expect(result.current.distribution).toEqual(DIST_A);

    rerender({ termsKey: "", shape: SHAPE_A });

    expect(result.current).toEqual({ distribution: null, loading: false, error: null });
  });
});

describe("取得", () => {
  it("最初の鍵は待たずにその時の形で取りに行き、届くまでは取得中で、届くと分布を返す", async () => {
    const held = heldReplies();
    onSameOrigin("POST", PREVIEW, held.reply);
    const { result } = mount({ termsKey: "k1", shape: SHAPE_A });
    await advance();

    expect(result.current).toEqual({ distribution: null, loading: true, error: null });

    await held.answer(0, Response.json(DIST_A));
    await advance();

    expect(result.current).toEqual({ distribution: DIST_A, loading: false, error: null });
  });

  it("鍵が変わっても間引きの間は取りに行かず、続けて変えたら最後の鍵の形で取る", async () => {
    serveDistributions();
    const { result, rerender } = mount({ termsKey: "k1", shape: SHAPE_A });
    await advance();

    rerender({ termsKey: "k2", shape: SHAPE_C });
    await advance(MAP_FETCH_DEBOUNCE_MS - 1);
    rerender({ termsKey: "k3", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS - 1);
    expect(result.current).toEqual({ distribution: DIST_A, loading: false, error: null });

    await advance(1);
    await advance();

    expect(result.current).toEqual({ distribution: DIST_B, loading: false, error: null });
  });

  it("取り直している間は前の分布を出したまま取得中を示し、届くと入れ替わる", async () => {
    serveDistributions();
    const { result, rerender } = mount({ termsKey: "k1", shape: SHAPE_A });
    await advance();
    const held = heldReplies();
    onSameOrigin("POST", PREVIEW, held.reply);

    rerender({ termsKey: "k2", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS);

    expect(result.current).toEqual({ distribution: DIST_A, loading: true, error: null });

    await held.answer(0, Response.json(DIST_B));
    await advance();

    expect(result.current).toEqual({ distribution: DIST_B, loading: false, error: null });
  });

  it("鍵が同じまま形だけ変わっても取り直さず、次に鍵が変わったときは最新の形で取る", async () => {
    serveDistributions();
    const { result, rerender } = mount({ termsKey: "k1", shape: SHAPE_A });
    await advance();

    rerender({ termsKey: "k1", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS);
    expect(result.current).toEqual({ distribution: DIST_A, loading: false, error: null });

    rerender({ termsKey: "k2", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS);
    await advance();

    expect(result.current).toEqual({ distribution: DIST_B, loading: false, error: null });
  });
});

describe("失敗", () => {
  it("失敗は理由の文言を返し、分布は出さない", async () => {
    onSameOrigin("POST", PREVIEW, () => Response.json({ detail: "分布の取得: 500" }, { status: 500 }));
    const { result } = mount({ termsKey: "k1", shape: SHAPE_A });
    await advance();

    expect(result.current).toEqual({ distribution: null, loading: false, error: "分布の取得: 500" });
  });
});
