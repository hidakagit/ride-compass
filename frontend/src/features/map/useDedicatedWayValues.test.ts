import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchDynamicWayValues } = vi.hoisted(() => ({ fetchDynamicWayValues: vi.fn() }));
vi.mock("@/services/regionApi", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  fetchDynamicWayValues,
}));
// 待ち時間の間引き自体はuseDebouncedValueの持ち物。ここは値が届いた後の振る舞いを見る。
vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import { catalogOf, dedicatedEntry } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import type { MapViewport } from "@/features/map/layers/windLayer";

import { useDedicatedWayValues } from "./useDedicatedWayValues";

const { dedicatedAxes } = catalogOf([
  dedicatedEntry("timed", [1], {
    dynamic_way_value_needs_time: true,
    dynamic_way_value_needs_bearing: true,
    dynamic_way_value_needs_speed: true,
  }),
  dedicatedEntry("static", [1]),
]);
const [TIMED, STATIC] = dedicatedAxes;
// z14で横2枚×縦1枚のタイルにまたがる範囲
const VIEWPORT: MapViewport = { west: 139.76, south: 35.68, east: 139.77, north: 35.685, zoom: 14 };
const AT = new Date("2026-09-24T00:00:00Z");

async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  fetchDynamicWayValues.mockReset().mockImplementation(async (axisId: string, z: number, x: number) => ({
    values: { [`${axisId}-${x}`]: x },
    error: false,
  }));
});

type Props = { axes: typeof dedicatedAxes; viewport: MapViewport | null; bearing: number; at: Date; speed?: number };
function render(initialProps: Props) {
  return renderHook(
    ({ axes, viewport, bearing, at, speed }: Props) => useDedicatedWayValues(axes, viewport, bearing, at, speed),
    { initialProps },
  );
}
const calledAxes = () => fetchDynamicWayValues.mock.calls.map((call) => call[0]);

describe("useDedicatedWayValues（専用配信の値）", () => {
  it("画面か対象の軸が無い間は取りに行かない", async () => {
    render({ axes: dedicatedAxes, viewport: null, bearing: 0, at: AT });
    render({ axes: [], viewport: VIEWPORT, bearing: 0, at: AT });
    await settle();
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
  });

  it("画面を覆うタイルごとに軸の値を取り、1つにまとめる", async () => {
    const { result } = render({ axes: [STATIC], viewport: VIEWPORT, bearing: 90, at: AT });
    await settle();
    const tileXs = fetchDynamicWayValues.mock.calls.map((call) => call[2]);
    expect(new Set(tileXs).size).toBeGreaterThan(1);
    expect(result.current.get("static")).toEqual({
      values: new Map(tileXs.map((x) => [`static-${x}`, x])),
      loading: false,
      error: false,
      hasFetched: true,
    });
  });

  it("時刻・向き・想定速度は、要ると宣言した軸のリクエストにだけ載せる", async () => {
    render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT, speed: 22 });
    await settle();
    const argsOf = (axisId: string) => fetchDynamicWayValues.mock.calls.find((call) => call[0] === axisId)!.slice(4);
    expect(argsOf("timed")).toEqual([90, AT, 22]);
    expect(argsOf("static")).toEqual([undefined, undefined, undefined]);
  });

  it("入力が変わった軸だけを取り直し、取り直す間は前の値を残して読み込み中にする", async () => {
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT });
    await settle();
    const staticBefore = result.current.get("static");
    fetchDynamicWayValues.mockClear();
    const pending: ((value: unknown) => void)[] = [];
    fetchDynamicWayValues.mockImplementation(() => new Promise((resolve) => pending.push(resolve)));

    rerender({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 180, at: AT });
    await settle();
    expect(new Set(calledAxes())).toEqual(new Set(["timed"]));
    expect(result.current.get("timed")).toMatchObject({ loading: true, hasFetched: true });
    expect(result.current.get("timed")?.values.size).toBeGreaterThan(0);
    expect(result.current.get("static")).toBe(staticBefore);

    pending.forEach((resolve) => resolve({ values: { next: 1 }, error: false }));
    await settle();
    expect(result.current.get("timed")?.loading).toBe(false);
  });

  it("入力が何も変わらなければ取り直さず、結果の参照も変えない", async () => {
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 90, at: AT });
    await settle();
    const before = result.current;
    fetchDynamicWayValues.mockClear();
    rerender({ axes: dedicatedAxes, viewport: { ...VIEWPORT }, bearing: 90, at: AT });
    await settle();
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
    expect(result.current).toBe(before);
  });

  it("1枚でもタイルの取得に失敗すれば失敗として返す", async () => {
    fetchDynamicWayValues.mockImplementation(async (_axisId: string, _z: number, x: number) =>
      x % 2 === 0 ? { values: {}, error: true } : { values: { a: 1 }, error: false },
    );
    const { result } = render({ axes: [STATIC], viewport: VIEWPORT, bearing: 0, at: AT });
    await settle();
    expect(result.current.get("static")?.error).toBe(true);
  });

  it("対象から外れた軸の結果は落とし、画面が無くなれば空へ戻す", async () => {
    const { result, rerender } = render({ axes: dedicatedAxes, viewport: VIEWPORT, bearing: 0, at: AT });
    await settle();
    rerender({ axes: [STATIC], viewport: VIEWPORT, bearing: 0, at: AT });
    await settle();
    expect([...result.current.keys()]).toEqual(["static"]);
    rerender({ axes: [STATIC], viewport: null, bearing: 0, at: AT });
    await settle();
    expect(result.current.size).toBe(0);
  });

  it("入力を変えた後に前の入力の答えが届いても使わない", async () => {
    const pending: ((value: unknown) => void)[] = [];
    fetchDynamicWayValues.mockImplementation(() => new Promise((resolve) => pending.push(resolve)));
    const { result, rerender } = render({ axes: [TIMED], viewport: VIEWPORT, bearing: 0, at: AT });
    await settle();
    const firstBatch = pending.splice(0);
    rerender({ axes: [TIMED], viewport: VIEWPORT, bearing: 45, at: AT });
    await settle();
    pending.splice(0).forEach((resolve) => resolve({ values: { fresh: 1 }, error: false }));
    await settle();
    firstBatch.forEach((resolve) => resolve({ values: { stale: 1 }, error: false }));
    await settle();
    expect([...(result.current.get("timed")?.values.keys() ?? [])]).toEqual(["fresh"]);
  });
});
