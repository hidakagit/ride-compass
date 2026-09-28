/**
 * 軸スタジオの生値分布の取得（`features/admin/useAxisValueDistribution.ts: useAxisValueDistribution`）——分布の形を決める鍵が落ち着いてから取りに行き、
 * 取り直している間は前の分布を出したまま取得中を示し、失敗を文言で返す。
 *
 * ここで見ないもの:
 * - 分布を描く・各階級の点数 → `AxisStudio/`の部品と`useScoresPreview.ts`
 * - 鍵（`termsKey`）の組み立て → 呼び出し元の部品
 * - 間引きの待ち方そのもの → `hooks/useDebouncedValue.ts`（ここでは本物を通し、時計を進める）
 *
 * 差し替えたもの: backendを呼ぶ口（`features/admin/adminApi.ts: fetchAxisValueDistribution`）。応答はテストが決める。
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ValueDistribution } from "@/features/admin/AxisStudio/scoreDistribution";
import { MAP_FETCH_DEBOUNCE_MS } from "@/hooks/useDebouncedValue";
import type { AxisShape } from "@/types/route";

const api = vi.hoisted(() => ({ fetchAxisValueDistribution: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import { useAxisValueDistribution } from "./useAxisValueDistribution";

const SHAPE_A = { kind: "linear", terms: [{ material_id: "num_a", weight: 1 }] } as unknown as AxisShape;
const SHAPE_B = { kind: "linear", terms: [{ material_id: "num_b", weight: 1 }] } as unknown as AxisShape;
const DIST_A = { edges: [0, 1], counts: [3] } as unknown as ValueDistribution;
const DIST_B = { edges: [0, 2], counts: [5] } as unknown as ValueDistribution;

interface Args {
  enabled: boolean;
  termsKey: string;
  shape: AxisShape;
}

function mount(initial: Args) {
  return renderHook(({ enabled, termsKey, shape }: Args) => useAxisValueDistribution(enabled, termsKey, () => shape), {
    initialProps: initial,
  });
}

/** 時計を進め、取得の結果が届くまでの区切りも流す。 */
async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** 解決を手で決められる応答。 */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("取りに行かないとき", () => {
  it.each([
    ["無効", { enabled: false, termsKey: "k1", shape: SHAPE_A }],
    ["鍵が空", { enabled: true, termsKey: "", shape: SHAPE_A }],
  ])("%sなら、分布も取得中も失敗も無く、問い合わせない", async (_, args) => {
    const { result } = mount(args);
    await advance(MAP_FETCH_DEBOUNCE_MS);

    expect(result.current).toEqual({ distribution: null, loading: false, error: null });
    expect(api.fetchAxisValueDistribution).not.toHaveBeenCalled();
  });

  it("取れた後に無効へ変わると、分布を出さない", async () => {
    api.fetchAxisValueDistribution.mockResolvedValue(DIST_A);
    const { result, rerender } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();
    expect(result.current.distribution).toEqual(DIST_A);

    rerender({ enabled: false, termsKey: "k1", shape: SHAPE_A });

    expect(result.current).toEqual({ distribution: null, loading: false, error: null });
  });
});

describe("取得", () => {
  it("最初の鍵は待たずにその時の形で取りに行き、届くまでは取得中で、届くと分布を返す", async () => {
    const response = deferred<ValueDistribution>();
    api.fetchAxisValueDistribution.mockReturnValue(response.promise);
    const { result } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();

    expect(api.fetchAxisValueDistribution).toHaveBeenCalledExactlyOnceWith(SHAPE_A);
    expect(result.current).toEqual({ distribution: null, loading: true, error: null });

    response.resolve(DIST_A);
    await advance();

    expect(result.current).toEqual({ distribution: DIST_A, loading: false, error: null });
  });

  it("鍵が変わっても間引きの間は取りに行かず、続けて変えたら最後の鍵を1回だけ取る", async () => {
    api.fetchAxisValueDistribution.mockResolvedValue(DIST_A);
    const { rerender } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();
    api.fetchAxisValueDistribution.mockClear();

    rerender({ enabled: true, termsKey: "k2", shape: SHAPE_A });
    await advance(MAP_FETCH_DEBOUNCE_MS - 1);
    rerender({ enabled: true, termsKey: "k3", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS - 1);
    expect(api.fetchAxisValueDistribution).not.toHaveBeenCalled();

    await advance(1);

    expect(api.fetchAxisValueDistribution).toHaveBeenCalledExactlyOnceWith(SHAPE_B);
  });

  it("取り直している間は前の分布を出したまま取得中を示し、届くと入れ替わる", async () => {
    api.fetchAxisValueDistribution.mockResolvedValue(DIST_A);
    const { result, rerender } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();
    const response = deferred<ValueDistribution>();
    api.fetchAxisValueDistribution.mockReturnValue(response.promise);

    rerender({ enabled: true, termsKey: "k2", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS);

    expect(result.current).toEqual({ distribution: DIST_A, loading: true, error: null });

    response.resolve(DIST_B);
    await advance();

    expect(result.current).toEqual({ distribution: DIST_B, loading: false, error: null });
  });

  it("鍵が同じまま形だけ変わっても取り直さず、次に鍵が変わったときは最新の形で取る", async () => {
    api.fetchAxisValueDistribution.mockResolvedValue(DIST_A);
    const { rerender } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();
    api.fetchAxisValueDistribution.mockClear();

    rerender({ enabled: true, termsKey: "k1", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS);
    expect(api.fetchAxisValueDistribution).not.toHaveBeenCalled();

    rerender({ enabled: true, termsKey: "k2", shape: SHAPE_B });
    await advance(MAP_FETCH_DEBOUNCE_MS);

    expect(api.fetchAxisValueDistribution).toHaveBeenCalledExactlyOnceWith(SHAPE_B);
  });
});

describe("失敗", () => {
  it("失敗は理由の文言を返し、分布は出さない", async () => {
    api.fetchAxisValueDistribution.mockRejectedValue(new Error("分布の取得: 500"));
    const { result } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();

    expect(result.current).toEqual({ distribution: null, loading: false, error: "分布の取得: 500" });
  });

  it("理由の無い失敗は、決まった文言を返す", async () => {
    api.fetchAxisValueDistribution.mockRejectedValue("timeout");
    const { result } = mount({ enabled: true, termsKey: "k1", shape: SHAPE_A });
    await advance();

    expect(result.current).toEqual({ distribution: null, loading: false, error: "分布の取得に失敗しました" });
  });
});
