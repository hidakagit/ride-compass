/**
 * `useMapAxisCatalog.ts`——軸カタログの応答から、地図だけが読むもの（地図の表示の軸・タイルの世代）を導くこと。
 *
 * 差し替えたもの: 軸カタログの応答（網の層）はテストが決める。
 * 軸は架空のもの（`testing/catalogAxes.ts`）。
 */
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse, rampEntry } from "@/testing/catalogAxes";
import regionTileConfig from "@/types/generated/region-tile-config.json";

import { useMapAxisCatalog } from "./useMapAxisCatalog";

const ALL_TILE_VERSIONS = Object.fromEntries(regionTileConfig.tile_version_kinds.map((kind) => [kind, `v-${kind}`]));

describe("useMapAxisCatalog", () => {
  it("軸スタジオで公開した軸のうち、地図の表示がrampの軸を塗る軸として、チップに出す軸を推定指標として返す", async () => {
    serveAxisCatalog(
      catalogResponse([
        catalogEntry({ axis_id: "not_on_map", show_map_icon: true }),
        rampEntry("published", [10], { show_map_icon: true }),
      ]),
    );

    const { result } = renderHook(() => useMapAxisCatalog());

    await waitFor(() => expect(result.current.rampAxes.map((axis) => axis.axisId)).toEqual(["published"]));
    expect(result.current.secondaryAxes.map((axis) => axis.axisId)).toEqual(["not_on_map", "published"]);
  });

  it("全系統が揃ったタイルの世代を返す（揃ったかの判定は`regionApi.test.ts`が見る）", async () => {
    serveAxisCatalog(catalogResponse([], { tile_versions: ALL_TILE_VERSIONS }));

    const { result } = renderHook(() => useMapAxisCatalog());

    await waitFor(() => expect(result.current.tileVersions).toEqual(ALL_TILE_VERSIONS));
  });

  it("共有の軸カタログと同じ取得の結果から導く", async () => {
    serveAxisCatalog(catalogResponse([rampEntry("ramp", [10])]));

    const shared = renderHook(() => useAxisCatalog());
    const map = renderHook(() => useMapAxisCatalog());

    await waitFor(() => expect(map.result.current.rampAxes).toHaveLength(1));
    expect(shared.result.current.axes.map((axis) => axis.axisId)).toEqual(["ramp"]);
  });
});
