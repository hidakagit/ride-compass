/**
 * `useDedicatedWayValues.ts`——専用配信の軸の道ごとの値を、画面のタイルと走行の条件で取り、軸ごとにまとめること。
 *
 * ここで見ないもの:
 * - 画面か対象の軸が無い間は取りに行かないこと → 読むだけの要求なので送ったかを見ない（testing.md「確かめる高さ」）。
 *   要求はタイルと軸の組から作るので、どちらかが無ければ1件も作られない。画面が無くなれば空へ戻すことは下のテストが見る
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 待ち時間の間引き自体はuseDebouncedValueの持ち物。ここは値が届いた後の振る舞いを見る。
vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import { heldReplies, onBackend } from "@/testing/backendServer";
import { mapCatalogOf } from "@/testing/mapAxisCatalog";
import { dedicatedEntry } from "@/testing/catalogAxes";
import type { MapViewport } from "@/features/map/layers/windLayer";

import { useDedicatedWayValues } from "./useDedicatedWayValues";

const { dedicatedAxes } = mapCatalogOf([
  dedicatedEntry("timed", [1], { dynamic_way_value_conditions: ["at", "bearing_deg", "speed_kmh"] }),
  dedicatedEntry("static", [1]),
]);
const [, STATIC] = dedicatedAxes;
// z14で横2枚×縦1枚のタイルにまたがる範囲
const VIEWPORT: MapViewport = { west: 139.76, south: 35.68, east: 139.77, north: 35.685, zoom: 14 };
const AT = new Date("2026-09-24T00:00:00Z");
const SPEED_KMH = 20;

const WAY_VALUES = "/api/region/dynamic-way-values/:axisId/:z/:x/:y";

/**
 * 道ごとの値の代役。問われた軸・タイルのx・条件（向き|時刻|速度。無ければ`-`）を道の鍵`軸@x@条件`に書き、
 * 値にタイルのxを返す。`failsAt`が真を返すタイルは失敗で答える。
 */
function serveWayValues(failsAt: (x: number) => boolean = () => false) {
  onBackend("GET", WAY_VALUES, ({ path, query }) => {
    const [axisId, , x] = path.split("/").slice(-4);
    if (failsAt(Number(x))) return new Response(null, { status: 500 });
    const conditions = [query.bearing_deg, query.at, query.speed_kmh].map((value) => value ?? "-").join("|");
    return Response.json({ [`${axisId}@${x}@${conditions}`]: Number(x) });
  });
}

type Results = { current: ReturnType<typeof useDedicatedWayValues> };

// 取得の結果は網を通って届くので、偽にしていない時計で、どの軸も取り終えるまで待つ（届くまでの時間は CI の負荷で変わる）。
async function fetched(result: Results) {
  await vi.waitFor(() => {
    expect(result.current.size).toBeGreaterThan(0);
    for (const axis of result.current.values()) expect(axis).toMatchObject({ loading: false, hasFetched: true });
  });
}

/** 取り直しが起きていれば応答が届くだけの間をおく（起きないことを確かめるため）。 */
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 50)));

beforeEach(() => {
  serveWayValues();
});

type Props = { axes: typeof dedicatedAxes; viewport: MapViewport | null; bearing: number; at: Date; speed?: number };
function render(initialProps: Props) {
  return renderHook(
    ({ axes, viewport, bearing, at, speed }: Props) =>
      useDedicatedWayValues(axes, viewport, bearing, at, speed ?? SPEED_KMH),
    { initialProps },
  );
}
const wayKeys = (values: ReadonlyMap<string, number | null> | undefined) => [...(values?.keys() ?? [])];

describe("useDedicatedWayValues（専用配信の値）", () => {
  it("画面を覆うタイルごとに軸の値を取り、1つにまとめる", async () => {
    const { result } = render({ axes: [STATIC], viewport: VIEWPORT, bearing: 90, at: AT });
    await fetched(result);
    const values = result.current.get("static")!.values;
    expect(new Set(values.values()).size).toBeGreaterThan(1);
    expect([...values].every(([key, x]) => key.startsWith(`static@${x}@`))).toBe(true);
    expect(result.current.get("static")).toMatchObject({ loading: false, error: false, hasFetched: true });
  });

  it("時刻・向き・想定速度は、要ると宣言した軸のリクエストにだけ載せる", async () => {
    const { result } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT, speed: 22 });
    await fetched(result);
    const conditionsOf = (axisId: string) =>
      new Set(wayKeys(result.current.get(axisId)?.values).map((key) => key.split("@")[2]));
    expect(conditionsOf("timed")).toEqual(new Set([`90|${AT.toISOString()}|22`]));
    expect(conditionsOf("static")).toEqual(new Set(["-|-|-"]));
  });

  it("入力が変わった軸だけを取り直し、取り直す間は前の値を残して読み込み中にする", async () => {
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT });
    await fetched(result);
    const staticBefore = result.current.get("static");
    const held = heldReplies();
    onBackend("GET", WAY_VALUES, held.reply);

    rerender({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 180, at: AT });
    await vi.waitFor(() => expect(held.arrived()).toBeGreaterThan(0));
    expect(result.current.get("timed")).toMatchObject({ loading: true, hasFetched: true });
    expect(result.current.get("timed")?.values.size).toBeGreaterThan(0);
    expect(result.current.get("static")).toBe(staticBefore);

    for (let index = 0; index < held.arrived(); index += 1) await held.answer(index, Response.json({ next: 1 }));
    await vi.waitFor(() => expect(result.current.get("timed")?.loading).toBe(false));
  });

  it("入力が何も変わらなければ取り直さず、結果の参照も変えない", async () => {
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT });
    await fetched(result);
    const before = result.current;
    rerender({ axes: dedicatedAxes, viewport: { ...VIEWPORT }, bearing: 90, at: AT });
    await settle();
    expect(result.current).toBe(before);
  });

  it("取得に失敗した軸は、入力が同じでも次に取り直すときに一緒に取り直す", async () => {
    serveWayValues(() => true);
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 0, at: AT });
    await fetched(result);
    expect(result.current.get("static")?.error).toBe(true);
    serveWayValues();
    rerender({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT });
    await vi.waitFor(() => expect(result.current.get("static")?.error).toBe(false));
    expect(result.current.get("static")?.values.size).toBeGreaterThan(0);
  });
  it("対象から外れた軸の結果は落とし、画面が無くなれば空へ戻す", async () => {
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 0, at: AT });
    await fetched(result);
    rerender({ axes: [STATIC], viewport: VIEWPORT, bearing: 0, at: AT });
    await fetched(result);
    expect([...result.current.keys()]).toEqual(["static"]);
    rerender({ axes: [STATIC], viewport: null, bearing: 0, at: AT });
    await settle();
    expect(result.current.size).toBe(0);
  });
});
