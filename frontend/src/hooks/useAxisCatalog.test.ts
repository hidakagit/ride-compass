/**
 * 軸カタログの取得と共有（`hooks/useAxisCatalog.ts`）——読み手の間で1つの取得を共有し、届くまで・失敗の間は
 * 軸0件のカタログを返し（`loaded`・`failed`で見分ける）、一度届いた応答は後の取得の失敗で巻き戻さない。
 * 取れていない間だけヘッダーの印の項目を出し、その再試行は取れていないときだけ取り直す。
 *
 * ここで見ないもの:
 * - 応答からカタログの各欄（軸・既定重み・表示名・色）を導く中身 → `lib/axisCatalog.ts: axisCatalogFromResponse` を読む側のテスト
 * - backendへの問い合わせの形（宛先・待ち時間） → `services/axisCatalogApi.test.ts`
 * - 地図だけが読む形（`useAxisCatalogSelect` の読み手） → 判断の無い詰め替えで、`app/page.test.tsx` が本物で通す
 * - 読み手が一時いなくなっても取得の結果を捨てないこと（`gcTime: Infinity`） → どのテストも通さない（既定の破棄は
 *   5分後で、テストの間に起きない）
 *
 * 差し替えたもの: 軸カタログの応答（網の層）。取得のキャッシュは `vitest.setup.ts` がテストごとに空にする。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { getQueryClient } from "@/lib/queryClient";
import { heldReplies, onBackend, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import { settle } from "@/testing/settle";
import type { AxisCatalogResponse } from "@/types/route";

import { axisCatalogFetchFailure, retryAxisCatalogFetch, useAxisCatalog, useAxisCatalogSelect } from "./useAxisCatalog";

const RESPONSE_A = catalogResponse([catalogEntry({ axis_id: "axis_a" })]);
const RESPONSE_B = catalogResponse([catalogEntry({ axis_id: "axis_a" }), catalogEntry({ axis_id: "axis_b" })]);

/** 届いた順に、テストが応えるまで応答を返さない取得。`resolve`・`reject`は、その番目の取得が届くまで待ってから応える。 */
function deferredFetches() {
  const held = heldReplies();
  onBackend("GET", "/api/axis-catalog", held.reply);
  const answer = (index: number, response: Response) => act(() => held.answer(index, response));
  return {
    arrived: held.arrived,
    resolve: (index: number, value: AxisCatalogResponse) => answer(index, Response.json(value)),
    reject: (index: number) => answer(index, new Response(null, { status: 503 })),
  };
}

function axisIds(catalog: ReturnType<typeof useAxisCatalog>) {
  return catalog.axes.map((axis) => axis.axisId);
}

describe("useAxisCatalog", () => {
  it("届くまでは軸0件で、取れても失敗してもいない", () => {
    deferredFetches();

    const { result } = renderHook(() => useAxisCatalog());

    expect(result.current.axes).toEqual([]);
    expect(result.current.loaded).toBe(false);
    expect(result.current.failed).toBe(false);
    expect(axisCatalogFetchFailure(result.current)).toBeNull();
  });

  it("届いたら、応答の軸を持つ取れたカタログになり、印の項目は無い", async () => {
    serveAxisCatalog(RESPONSE_A);

    const { result } = renderHook(() => useAxisCatalog());

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.failed).toBe(false);
    expect(axisIds(result.current)).toEqual(["axis_a"]);
    expect(axisCatalogFetchFailure(result.current)).toBeNull();
  });

  it("失敗したら軸0件の失敗したカタログになり、ヘッダーの印の項目が再試行を持って出る", async () => {
    onBackend("GET", "/api/axis-catalog", () => new Response(null, { status: 503 }));

    const { result } = renderHook(() => useAxisCatalog());

    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.loaded).toBe(false);
    expect(result.current.axes).toEqual([]);
    expect(axisCatalogFetchFailure(result.current)).not.toBeNull();
  });

  it("失敗の後の印の項目の再試行は取り直し、取り直している間は失敗を下ろし、取れたら印の項目が消える", async () => {
    const fetches = deferredFetches();
    const { result } = renderHook(() => useAxisCatalog());
    await fetches.reject(0);
    await waitFor(() => expect(result.current.failed).toBe(true));

    act(() => axisCatalogFetchFailure(result.current)!.onRetry!());

    await waitFor(() => expect(fetches.arrived()).toBe(2));
    expect(result.current.failed).toBe(false);
    expect(result.current.loaded).toBe(false);

    await fetches.resolve(1, RESPONSE_A);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(axisIds(result.current)).toEqual(["axis_a"]);
    expect(axisCatalogFetchFailure(result.current)).toBeNull();
  });

  it("取れた後の再試行は取り直さない", async () => {
    serveAxisCatalog(RESPONSE_A);
    const { result } = renderHook(() => useAxisCatalog());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    serveAxisCatalog(RESPONSE_B);

    act(() => retryAxisCatalogFetch());

    await settle();
    expect(axisIds(result.current)).toEqual(["axis_a"]);
  });

  it("後から描いた読み手は取り直し、その結果は先にいる読み手にも届く", async () => {
    const fetches = deferredFetches();
    const first = renderHook(() => useAxisCatalog());
    await fetches.resolve(0, RESPONSE_A);
    await waitFor(() => expect(first.result.current.loaded).toBe(true));

    const second = renderHook(() => useAxisCatalog());

    await waitFor(() => expect(fetches.arrived()).toBe(2));
    expect(axisIds(second.result.current)).toEqual(["axis_a"]);
    await fetches.resolve(1, RESPONSE_B);
    await waitFor(() => expect(axisIds(first.result.current)).toEqual(["axis_a", "axis_b"]));
    expect(axisIds(second.result.current)).toEqual(["axis_a", "axis_b"]);
  });

  it("一度届いた後の取り直しが失敗しても、届いたカタログのまま失敗にならない", async () => {
    const fetches = deferredFetches();
    const first = renderHook(() => useAxisCatalog());
    await fetches.resolve(0, RESPONSE_A);
    await waitFor(() => expect(first.result.current.loaded).toBe(true));

    const second = renderHook(() => useAxisCatalog());
    await waitFor(() => expect(fetches.arrived()).toBe(2));
    await fetches.reject(1);
    // 失敗が届いて取り直しが終わってから確かめる（取り直している間は、どの作りでも失敗にならない）。
    await waitFor(() => expect(getQueryClient().isFetching()).toBe(0));

    expect(second.result.current.failed).toBe(false);
    expect(axisIds(second.result.current)).toEqual(["axis_a"]);
  });
});

describe("useAxisCatalogSelect", () => {
  const countAxes = (response: AxisCatalogResponse) => response.axes.length;

  it("形の異なる読み手どうしも、取得は1つを共有し、それぞれ自分の導いた形で受け取る", async () => {
    const fetches = deferredFetches();

    const counted = renderHook(() => useAxisCatalogSelect(countAxes));
    const catalog = renderHook(() => useAxisCatalog());
    await fetches.resolve(0, RESPONSE_B);

    await waitFor(() => expect(counted.result.current.data).toBe(2));
    expect(axisIds(catalog.result.current)).toEqual(["axis_a", "axis_b"]);
  });
});
