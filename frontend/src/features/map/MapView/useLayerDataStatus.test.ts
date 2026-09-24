/**
 * `useLayerDataStatus.ts`——表示中のレイヤーごとに取得状態（取得中・空・失敗）を地図のソースから数え、変わったときだけ
 * 知らせ、失敗は新しい取得が始まったときか、範囲が動いて読み込みが落ち着いたときにだけ解除すること。
 *
 * 地図は状態を読む3つのメソッドだけを持つ模擬で与える。
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LayerDataStatusByLayer, MapLayerId } from "@/features/map/layers/mapLayers";
import {
  computeLayerDataStatus,
  type DataStatusMapLike,
  type LayerDataSourceEntry,
  useLayerDataStatus,
} from "./useLayerDataStatus";

interface FakeMapState {
  added?: string[];
  unloaded?: string[];
  empty?: string[];
  queries?: string[];
}

function fakeMap(state: FakeMapState): DataStatusMapLike {
  return {
    getSource: (id) => (state.added === undefined || state.added.includes(id) ? {} : undefined),
    isSourceLoaded: (id) => !(state.unloaded ?? []).includes(id),
    querySourceFeatures: (id, { sourceLayer }) => {
      state.queries?.push(`${id}/${sourceLayer}`);
      return (state.empty ?? []).includes(`${id}/${sourceLayer}`) ? [] : [{}];
    },
  };
}

const id = (key: string) => key as MapLayerId;
/** 2つのレイヤーが同じタイルを分け合い、1つは別のタイル、1つはsource-layerの無いラスタ。 */
const SOURCES: LayerDataSourceEntry[] = [
  { key: id("a"), sourceId: "road", sourceLayer: "lines" },
  { key: id("b"), sourceId: "road", sourceLayer: "lines" },
  { key: id("c"), sourceId: "points", sourceLayer: "poi" },
  { key: id("raster"), sourceId: "relief" },
];
const ALL_ON = { a: true, b: true, c: true, raster: true } as Partial<Record<MapLayerId, boolean>>;

describe("computeLayerDataStatus", () => {
  it("表示中のレイヤーだけを、失敗＞取得中＞空の順で判定し、正常なものはキーを持たない", () => {
    const map = fakeMap({ unloaded: ["points"], empty: ["road/lines"] });
    expect(computeLayerDataStatus(map, new Set(["relief"]), ALL_ON, SOURCES)).toEqual({
      a: "empty",
      b: "empty",
      c: "loading",
      raster: "error",
    });
    expect(computeLayerDataStatus(map, new Set(), { [id("c")]: true }, SOURCES)).toEqual({ c: "loading" });
    expect(computeLayerDataStatus(fakeMap({}), new Set(), ALL_ON, SOURCES)).toEqual({});
  });

  it("ソースがまだ地図に無いレイヤーは数えない。source-layerの無いラスタは空と判定しない", () => {
    const map = fakeMap({ added: ["relief"], empty: ["relief/undefined"] });
    expect(computeLayerDataStatus(map, new Set(), ALL_ON, SOURCES)).toEqual({});
  });

  it("同じタイルを分け合うレイヤーがいくつ見えていても、地物は1回だけ数える", () => {
    const queries: string[] = [];
    computeLayerDataStatus(fakeMap({ queries }), new Set(), ALL_ON, SOURCES);
    expect(queries.sort()).toEqual(["points/poi", "road/lines"]);
  });
});

function renderStatus(state: FakeMapState) {
  const onChange = vi.fn<(status: LayerDataStatusByLayer) => void>();
  const map = fakeMap(state);
  const { result } = renderHook(() =>
    useLayerDataStatus({ mapRef: { current: map }, layerDataSources: SOURCES, getVisibility: () => ALL_ON, onChange }),
  );
  return { hook: () => result.current, onChange, state };
}

describe("useLayerDataStatus", () => {
  it("失敗したソースのレイヤーを失敗として知らせ、追っていないソースの失敗は無視する", () => {
    const { hook, onChange } = renderStatus({});
    act(() => hook().markSourceErrored("untracked"));
    expect(onChange).not.toHaveBeenCalled();
    act(() => hook().markSourceErrored("road"));
    expect(onChange).toHaveBeenLastCalledWith({ a: "error", b: "error" });
  });

  it("状態が変わらなければ知らせない", () => {
    const { hook, onChange } = renderStatus({});
    act(() => hook().markSourceErrored("road"));
    act(() => hook().notifySourceData("road"));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("新しい取得が始まったら、失敗を解除する", () => {
    const { hook, onChange } = renderStatus({});
    act(() => hook().markSourceErrored("road"));
    act(() => hook().clearSourceLoading("road"));
    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it("範囲が動いて読み込みが落ち着いたソースだけ失敗を解除し、読み込み中のソースの失敗は残す", () => {
    const { hook, onChange, state } = renderStatus({});
    act(() => {
      hook().markSourceErrored("road");
      hook().markSourceErrored("points");
    });
    state.unloaded = ["points"];
    act(() => hook().settleViewport());
    expect(onChange).toHaveBeenLastCalledWith({ c: "error" });

    onChange.mockClear();
    act(() => hook().settleViewport());
    expect(onChange).not.toHaveBeenCalled();
  });
});
