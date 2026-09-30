import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { getAxisCatalog as GetAxisCatalog } from "@/services/axisCatalogApi";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

// 軸カタログの取得（通信は差し替え）と、機能をまたいで読む形の導出。地図だけが読む形は
// `features/map/useMapAxisCatalog.test.ts`が見る。
vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { CLIENT_TUNING_IDS, clientTuningValue } from "@/lib/axisCatalog";

// 届いたカタログは共有のキャッシュ（`lib/queryClient.ts`）に残る。**テストごとに読み込み直して
// 空のキャッシュから始める**——本番へ「テストのために戻す」口を置かないため（設計原則 構造仕様15）。
// 取得のモックも読み込み直しで作り直されるので、毎回こちらも取り直す。
let mod: typeof import("./useAxisCatalog");
let getAxisCatalog: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  vi.resetModules();
  ({ getAxisCatalog } = (await import("@/services/axisCatalogApi")) as unknown as {
    getAxisCatalog: ReturnType<typeof vi.fn>;
  });
  mod = await import("./useAxisCatalog");
});

type AxisCatalogResponse = Awaited<ReturnType<typeof GetAxisCatalog>>;

function catalogResponse(): AxisCatalogResponse {
  return {
    axes: [
      {
        axis_id: "surface_q",
        label: "舗装質",
        description: "",
        category: "観測",
        default_weight: 0.19,
        display: { kind: "none", label: "舗装質", category: "trafficSafety", tile_inputs: [], thresholds: [] },
        primary_attribute_ids: ["surface"],
        weather_layer_groups: [],
        icon_id: "wave",
        chip_label: "舗装",
        panel_hint: null,
        show_map_icon: true,
        shape: { kind: "categorical", material: "surface_estimate", mapping: { paved: 0, gravel: 80 } },
        display_thresholds_override: null,
        display_band_labels_override: null,
        dedicated_way_value_layer: false,
        map_value: { kind: "difficulty" },
        map_value_unit: "",
        map_value_thresholds: [33, 66],
        dynamic_way_value_needs_time: false,
        dynamic_way_value_needs_bearing: false,
        dynamic_way_value_needs_speed: false,
        raw_value_unit: null,
        raw_value_total_unit: null,
        material_breakdown: [],
      },
      // 軸スタジオで公開されたばかりの新規GUI軸（複数材料の重み付き結合、kind=ramp）。
      // 軸は実行時APIだけが配る（ビルド時の生成物は軸の写しを持たない）。
      {
        axis_id: "gui_published_axis",
        label: "GUI公開軸テスト",
        description: "",
        category: "推定",
        default_weight: 0.1,
        display: {
          kind: "ramp",
          label: "GUI公開軸テスト",
          category: "trafficSafety",
          tile_inputs: [
            {
              property: "lanes_count",
              weight: 1.0,
              boolean: false,
              true_value: 0,
              false_value: 0,
              has_unknown_fallback: false,
              categories: null,
              breakpoints: null,
              needs_runtime_scale: false,
            },
          ],
          thresholds: [10.0],
        },
        primary_attribute_ids: ["lanes"],
        weather_layer_groups: [],
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        show_map_icon: true,
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "lanes_count", weight: 1.0, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
        display_thresholds_override: null,
        display_band_labels_override: null,
        dedicated_way_value_layer: false,
        map_value: { kind: "difficulty" },
        map_value_unit: "",
        map_value_thresholds: [33, 66],
        dynamic_way_value_needs_time: false,
        dynamic_way_value_needs_bearing: false,
        dynamic_way_value_needs_speed: false,
        raw_value_unit: null,
        raw_value_total_unit: null,
        material_breakdown: [],
      },
    ],
    // tile_runtime_scalesはAxisCatalogResponseの必須フィールド
    // （既定{}だがopenapi-typescriptはdefault付きフィールドをoptionalにしない）。
    tile_runtime_scales: {},
    client_tuning: {},
    accident_years: [],
    tile_versions: {},
  };
}

describe("useAxisCatalog", () => {
  it("実行時フェッチが完了すると、軸スタジオで公開したばかりの軸も含めて軸の一覧・名前・既定重みを返す", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse());

    const { result } = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.axes.map((axis) => axis.axisId)).toEqual(["surface_q", "gui_published_axis"]);
    expect(result.current.axisLabels).toEqual({ surface_q: "舗装質", gui_published_axis: "GUI公開軸テスト" });
    expect(result.current.defaultWeights).toEqual({ surface_q: 0.19, gui_published_axis: 0.1 });
  });

  it("取得できるまでは較正値を引けず（ビルド時の既定で埋めない）、取得後はbackendの値を返す", async () => {
    // 管理画面から変えた値を再デプロイなしに画面へ届けるための経路。
    vi.mocked(getAxisCatalog).mockResolvedValue({
      ...catalogResponse(),
      client_tuning: { [CLIENT_TUNING_IDS.minStretchKm]: 0.5 },
    });

    const { result } = renderHook(() => mod.useAxisCatalog());

    expect(clientTuningValue(result.current, CLIENT_TUNING_IDS.minStretchKm)).toBeUndefined();
    await waitFor(() => expect(clientTuningValue(result.current, CLIENT_TUNING_IDS.minStretchKm)).toBe(0.5));
  });

  it("フロントが読む較正値は、どれもビルド時生成物に在る", () => {
    // backendの宣言（domain/tuning.py）から消す・綴りを変えると、フロントは引けないまま
    // その値を使う機能を黙って出さなくなる。生成物はexport_openapi.pyが宣言から作るため、ここで突き合わせると
    // その変更がフロント側のCIで落ちる。
    const ids = Object.values(CLIENT_TUNING_IDS);

    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      expect(Object.hasOwn(routeGenerateConfig.client_tuning, id)).toBe(true);
    }
  });

  it("改善計画T318フォローアップ: 全軸非公開でaxesが0件のレスポンスは、そのまま空を返す", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue({
      axes: [],
      tile_runtime_scales: {},
      client_tuning: {},
      accident_years: [],
      tile_versions: {},
    });

    const { result } = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.axes).toEqual([]);
    expect(result.current.axisLabels).toEqual({});
    expect(result.current.defaultWeights).toEqual({});
  });

  it("フェッチ失敗はfailed=trueとして表面化する（未取得[両方false]と区別できる）", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.loaded).toBe(false);
  });

  it("retryAxisCatalogFetchは再取得し、成功すればfailedが下りてカタログが入れ替わる", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValueOnce(new Error("network error"));
    const { result } = renderHook(() => mod.useAxisCatalog());
    await waitFor(() => expect(result.current.failed).toBe(true));

    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    mod.retryAxisCatalogFetch();

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.failed).toBe(false);
    expect(result.current.axes).toHaveLength(2);
  });

  it("取れていない間だけヘッダーの印の項目があり、その再試行で取れたら項目が消える", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValueOnce(new Error("network error"));
    const { result } = renderHook(() => mod.useAxisCatalog());
    expect(mod.axisCatalogFetchFailure(result.current)).toBeNull();
    await waitFor(() => expect(mod.axisCatalogFetchFailure(result.current)).toMatchObject({ id: "axis-catalog" }));

    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    mod.axisCatalogFetchFailure(result.current)?.onRetry?.();

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(mod.axisCatalogFetchFailure(result.current)).toBeNull();
  });

  it("取得成功後のretryAxisCatalogFetchは再取得しない（既に確定しているため）", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    const { result } = renderHook(() => mod.useAxisCatalog());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    const callsBefore = vi.mocked(getAxisCatalog).mock.calls.length;

    mod.retryAxisCatalogFetch();

    expect(vi.mocked(getAxisCatalog).mock.calls.length).toBe(callsBefore);
  });

  it("改善計画T527: 先にマウント済みの呼び出し元は、別の呼び出し元が後から再フェッチした結果も共有する", async () => {
    // page.tsxが先にマウントしてフェッチ完了した後、RouteSettingsPanel.tsxが再マウント
    // （モバイルのBottomSheetでタブを開き直す等）して再フェッチするシナリオ。以前は
    // 呼び出し元ごとに独立したuseStateだったため、firstは古いカタログのまま取り残され
    // secondとの間でaxes配列が食い違っていた。
    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    const first = renderHook(() => mod.useAxisCatalog());
    await waitFor(() => expect(first.result.current.loaded).toBe(true));
    expect(first.result.current.axes).toHaveLength(2);

    // 軸スタジオでgui_published_axisが非公開になり、以後のフェッチは1軸だけ返す想定。
    vi.mocked(getAxisCatalog).mockResolvedValueOnce({
      axes: [catalogResponse().axes[0]],
      tile_runtime_scales: {},
      client_tuning: {},
      accident_years: [],
      tile_versions: {},
    });
    const second = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => expect(second.result.current.axes).toHaveLength(1));
    // firstは自分では再フェッチしていないが、共有のキャッシュ経由で最新の1軸へ追従する。
    expect(first.result.current.axes).toEqual(second.result.current.axes);
  });

  it("改善計画T527: 後発の呼び出し元の再フェッチが失敗しても、既に取得済みの正常なカタログを巻き戻さない", async () => {
    // 呼び出し回数はテストファイル内で共有されるため、このテスト内での増分だけを見る。
    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    const first = renderHook(() => mod.useAxisCatalog());
    await waitFor(() => expect(first.result.current.loaded).toBe(true));
    const callsBefore = vi.mocked(getAxisCatalog).mock.calls.length;

    vi.mocked(getAxisCatalog).mockRejectedValueOnce(new Error("network error"));
    const second = renderHook(() => mod.useAxisCatalog());
    await waitFor(() => expect(vi.mocked(getAxisCatalog).mock.calls.length - callsBefore).toBe(1));

    // secondの再フェッチが失敗しても、firstが既に取得していた2軸のカタログのまま
    // （取得前の空へ巻き戻らない）。
    expect(first.result.current.loaded).toBe(true);
    expect(first.result.current.failed).toBe(false);
    expect(first.result.current.axes).toHaveLength(2);
    expect(second.result.current.axes).toHaveLength(2);
  });
});
