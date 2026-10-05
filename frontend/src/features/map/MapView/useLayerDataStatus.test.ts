/**
 * `useLayerDataStatus.ts`——表示中のレイヤーごとに取得状態（取得中・空・失敗）を地図のソースから数え、変わったときだけ
 * 知らせ、失敗は新しい取得が始まったときか、範囲が動いて読み込みが落ち着いたときにだけ解除すること。
 *
 * 地図は状態を読む3つのメソッドだけを持つ模擬で与える。
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LayerDataStatusByLayer, MapLayerId } from "@/features/map/layers/mapLayers";
import { useLayerDataStatus } from "./useLayerDataStatus";

type Args = Parameters<typeof useLayerDataStatus>[0];

interface FakeMapState {
  added?: string[];
  unloaded?: string[];
  empty?: string[];
}

function fakeMap(state: FakeMapState): NonNullable<Args["mapRef"]["current"]> {
  return {
    getSource: (id) => (state.added === undefined || state.added.includes(id) ? {} : undefined),
    isSourceLoaded: (id) => !(state.unloaded ?? []).includes(id),
    querySourceFeatures: (id, { sourceLayer }) => ((state.empty ?? []).includes(`${id}/${sourceLayer}`) ? [] : [{}]),
  };
}

const id = (key: string) => key as MapLayerId;
/** 2つのレイヤーが同じタイルを分け合い、1つは別のタイル、1つはsource-layerの無いラスタ。 */
const SOURCES: Args["layerDataSources"] = [
  { key: id("a"), sourceId: "road", sourceLayer: "lines" },
  { key: id("b"), sourceId: "road", sourceLayer: "lines" },
  { key: id("c"), sourceId: "points", sourceLayer: "poi" },
  { key: id("raster"), sourceId: "relief" },
];
const ALL_ON = { a: true, b: true, c: true, raster: true } as Partial<Record<MapLayerId, boolean>>;

function renderStatus(state: FakeMapState, visibility: Partial<Record<MapLayerId, boolean>> = ALL_ON) {
  const onChange = vi.fn<(status: LayerDataStatusByLayer) => void>();
  const map = fakeMap(state);
  const { result } = renderHook(() =>
    useLayerDataStatus({
      mapRef: { current: map },
      layerDataSources: SOURCES,
      getVisibility: () => visibility,
      onChange,
    }),
  );
  return { hook: () => result.current, onChange, state };
}

describe("useLayerDataStatus（数え方）", () => {
  it("表示中のレイヤーだけを、失敗＞取得中＞空の順で判定し、正常なものはキーを持たない", () => {
    const state = { unloaded: ["points"], empty: ["road/lines"] };
    const all = renderStatus(state);
    act(() => all.hook().markSourceErrored("relief"));
    expect(all.onChange).toHaveBeenLastCalledWith({ a: "empty", b: "empty", c: "loading", raster: "error" });

    const onlyC = renderStatus(state, { [id("c")]: true });
    act(() => onlyC.hook().recompute());
    expect(onlyC.onChange).toHaveBeenLastCalledWith({ c: "loading" });

    const healthy = renderStatus({});
    act(() => healthy.hook().recompute());
    expect(healthy.onChange).not.toHaveBeenCalled();
  });

  it("ソースがまだ地図に無いレイヤーは数えない。source-layerの無いラスタは空と判定しない", () => {
    const { hook, onChange } = renderStatus({ added: ["relief"], empty: ["relief/undefined"] });
    act(() => hook().recompute());
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("useLayerDataStatus（知らせ方と解除）", () => {
  it("新しい取得が始まったら失敗を解除し、届いた取得で数え直す", () => {
    const { hook, onChange, state } = renderStatus({});
    act(() => hook().markSourceErrored("road"));
    act(() => hook().clearSourceLoading("road"));
    expect(onChange).toHaveBeenLastCalledWith({});
    state.empty = ["road/lines"];
    act(() => hook().notifySourceData("road"));
    expect(onChange).toHaveBeenLastCalledWith({ a: "empty", b: "empty" });
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
  });
});
