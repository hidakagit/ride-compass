/**
 * `useMapAxisCatalog.ts`——軸カタログの応答から、地図だけが読むもの（地図の表示の軸・タイルの世代）を導くこと。
 *
 * 差し替えた部品: 軸カタログの通信（`services/axisCatalogApi.getAxisCatalog`）は返す値をテストが決める。
 * 軸は架空のもの（`testing/catalogAxes.ts`）。
 */
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { catalogEntry, catalogResponse, rampEntry } from "@/testing/catalogAxes";
import regionTileConfig from "@/types/generated/region-tile-config.json";

vi.mock("@/services/axisCatalogApi", () => ({ getAxisCatalog: vi.fn() }));

// 届いた応答は共有のキャッシュ（`lib/queryClient.ts`）に残るため、テストごとに読み込み直して空から始める。
let mapHook: typeof import("./useMapAxisCatalog");
let sharedHook: typeof import("@/hooks/useAxisCatalog");
let getAxisCatalog: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  vi.resetModules();
  ({ getAxisCatalog } = (await import("@/services/axisCatalogApi")) as unknown as {
    getAxisCatalog: ReturnType<typeof vi.fn>;
  });
  mapHook = await import("./useMapAxisCatalog");
  sharedHook = await import("@/hooks/useAxisCatalog");
});

const ALL_TILE_VERSIONS = Object.fromEntries(regionTileConfig.tile_version_kinds.map((kind) => [kind, `v-${kind}`]));

describe("useMapAxisCatalog", () => {
  it("軸スタジオで公開した軸のうち、地図の表示がrampの軸を塗る軸として、チップに出す軸を推定指標として返す", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(
      catalogResponse([
        catalogEntry({ axis_id: "not_on_map", show_map_icon: true }),
        rampEntry("published", [10], { show_map_icon: true }),
      ]),
    );

    const { result } = renderHook(() => mapHook.useMapAxisCatalog());

    await waitFor(() => expect(result.current.rampAxes.map((axis) => axis.axisId)).toEqual(["published"]));
    expect(result.current.secondaryAxes.map((axis) => axis.axisId)).toEqual(["not_on_map", "published"]);
  });

  it("全系統が揃ったタイルの世代を返す（揃ったかの判定は`regionApi.test.ts`が見る）", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse([], { tile_versions: ALL_TILE_VERSIONS }));

    const { result } = renderHook(() => mapHook.useMapAxisCatalog());

    await waitFor(() => expect(result.current.tileVersions).toEqual(ALL_TILE_VERSIONS));
  });

  it("共有の軸カタログと同じ取得の結果から導く", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse([rampEntry("ramp", [10])]));

    const shared = renderHook(() => sharedHook.useAxisCatalog());
    const map = renderHook(() => mapHook.useMapAxisCatalog());

    await waitFor(() => expect(map.result.current.rampAxes).toHaveLength(1));
    expect(shared.result.current.axes.map((axis) => axis.axisId)).toEqual(["ramp"]);
  });
});
