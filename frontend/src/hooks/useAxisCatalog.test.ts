import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

// 改善計画T308: useAxisCatalogがrampAxes/axisLabels/secondaryAxesを実行時APIから
// 導出することの回帰テスト。RouteSettingsPanel.test.tsxと同じモック方針。
vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { CLIENT_TUNING_IDS } from "@/lib/axisCatalog";

// このフックは、複数の呼び出し元へ同じカタログを配るためにモジュールスコープのストアを
// 持つ。**テストごとに読み込み直して初期状態へ戻す**——本番へ「テストのために戻す」口を
// 置かないため（設計原則 構造仕様15）。取得のモックも読み込み直しで作り直されるので、
// 毎回こちらも取り直す。
let mod: typeof import("./useAxisCatalog");
let getAxisCatalog: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  vi.resetModules();
  ({ getAxisCatalog } = (await import("@/services/axisCatalogApi")) as unknown as {
    getAxisCatalog: ReturnType<typeof vi.fn>;
  });
  mod = await import("./useAxisCatalog");
});

function catalogResponse(): AxisCatalogResponse {
  return {
    axes: [
      {
        axis_id: "surface_q",
        label: "舗装質",
        description: "",
        category: "観測",
        default_weight: 0.19,
        display: { kind: "none", label: "舗装質", category: "trafficSafety" },
        primary_attribute_ids: ["surface"],
        icon_id: "wave",
        chip_label: "舗装",
        panel_hint: null,
        show_map_icon: true,
        shape: { kind: "categorical", material: "surface_good", mapping: { true: 0, false: 80 } },
        display_thresholds_override: null,
        display_band_labels_override: null,
        dedicated_way_value_layer: false,
        map_value_kind: "difficulty",
        map_value_material: null,
        map_value_unit: "",
        map_value_thresholds: null,
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
              needs_runtime_scale: false,
            },
          ],
          thresholds: [10.0],
        },
        primary_attribute_ids: ["lanes"],
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
        map_value_kind: "difficulty",
        map_value_material: null,
        map_value_unit: "",
        map_value_thresholds: null,
        dynamic_way_value_needs_time: false,
        dynamic_way_value_needs_bearing: false,
        dynamic_way_value_needs_speed: false,
        raw_value_unit: null,
        raw_value_total_unit: null,
        material_breakdown: [],
      },
    ],
    // 改善計画T404: material_runtime_scalesはAxisCatalogResponseの必須フィールド
    // （既定{}だがopenapi-typescriptはdefault付きフィールドをoptionalにしない）。
    material_runtime_scales: {},
    client_tuning: {},
    accident_years: [],
    tile_versions: {},
  };
}

describe("useAxisCatalog（改善計画T308: rampAxes/axisLabels/secondaryAxesの実行時フェッチ）", () => {
  it("実行時フェッチが完了すると、GUI公開軸を含むrampAxesを返す", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse());

    const { result } = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => {
      expect(result.current.rampAxes.some((axis) => axis.axisId === "gui_published_axis")).toBe(true);
    });

    const guiAxis = result.current.rampAxes.find((axis) => axis.axisId === "gui_published_axis")!;
    expect(guiAxis.tileInputs).toEqual([
      {
        property: "lanes_count",
        weight: 1.0,
        boolean: false,
        trueValue: 0,
        falseValue: 0,
        hasUnknownFallback: false,
        categories: undefined,
        breakpoints: undefined,
      },
    ]);
    expect(guiAxis.thresholds).toEqual([10.0]);
    // kind=noneのsurface_qはrampAxesには含まれないが、axisLabels/secondaryAxesには含まれる。
    expect(result.current.rampAxes.some((axis) => axis.axisId === "surface_q")).toBe(false);
    expect(result.current.axisLabels.gui_published_axis).toBe("GUI公開軸テスト");
    expect(result.current.axisLabels.surface_q).toBe("舗装質");
    const guiSecondaryAxis = result.current.secondaryAxes.find((axis) => axis.axisId === "gui_published_axis");
    expect(guiSecondaryAxis?.primaryAttributeIds).toEqual(["lanes"]);
  });

  it("取得できるまではビルド時の既定を、取得後はbackendの値を較正値として返す", async () => {
    // 管理画面から変えた値を再デプロイなしに画面へ届けるための経路。
    vi.mocked(getAxisCatalog).mockResolvedValue({
      ...catalogResponse(),
      client_tuning: { "splice.min_stretch_km": 0.5 },
    });

    const { result } = renderHook(() => mod.useAxisCatalog());

    expect(result.current.clientTuning["splice.min_stretch_km"]).toBe(
      routeGenerateConfig.client_tuning["splice.min_stretch_km"],
    );
    await waitFor(() => expect(result.current.clientTuning["splice.min_stretch_km"]).toBe(0.5));
  });

  it("フロントが読む較正値は、どれもビルド時生成物に在る", () => {
    // backendの宣言（domain/tuning.py）から消す・綴りを変えると、フロントは引けないまま
    // 黙って別の値で動く。生成物はexport_openapi.pyが宣言から作るため、ここで突き合わせると
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
      material_runtime_scales: {},
      client_tuning: {},
      accident_years: [],
      tile_versions: {},
    });

    const { result } = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => expect(result.current.axes).toEqual([]));
    expect(result.current.rampAxes).toEqual([]);
    expect(result.current.axisLabels).toEqual({});
    expect(result.current.secondaryAxes).toEqual([]);
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

  it("取得成功後のretryAxisCatalogFetchは再取得しない（既に確定しているため）", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    const { result } = renderHook(() => mod.useAxisCatalog());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    const callsBefore = vi.mocked(getAxisCatalog).mock.calls.length;

    mod.retryAxisCatalogFetch();

    expect(vi.mocked(getAxisCatalog).mock.calls.length).toBe(callsBefore);
  });

  it("コードレビュー指摘の修正確認: 同時にマウントされた複数の呼び出し元は1回のフェッチを共有する", async () => {
    // page.tsx・RouteSettingsPanel.tsxが同時にuseAxisCatalog()を呼ぶ初回描画のシナリオ
    // （以前は呼び出し元の数だけGET /api/axis-catalogが同時に飛んでいた）。
    // 呼び出し回数はvi.mocked(getAxisCatalog)がテストファイル内で共有される（このテスト単体
    // では自動リセットされない）ため、このテスト内での増分だけを見る。
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse());
    const callsBefore = vi.mocked(getAxisCatalog).mock.calls.length;

    const first = renderHook(() => mod.useAxisCatalog());
    const second = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => {
      expect(first.result.current.rampAxes.some((axis) => axis.axisId === "gui_published_axis")).toBe(true);
      expect(second.result.current.rampAxes.some((axis) => axis.axisId === "gui_published_axis")).toBe(true);
    });
    expect(vi.mocked(getAxisCatalog).mock.calls.length - callsBefore).toBe(1);
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
      material_runtime_scales: {},
      client_tuning: {},
      accident_years: [],
      tile_versions: {},
    });
    const second = renderHook(() => mod.useAxisCatalog());

    await waitFor(() => expect(second.result.current.axes).toHaveLength(1));
    // firstは自分では再フェッチしていないが、共有ストア経由で最新の1軸へ追従する。
    expect(first.result.current.axes).toHaveLength(1);
    expect(first.result.current.axes).toBe(second.result.current.axes);
  });

  it("改善計画T527: 後発の呼び出し元の再フェッチが失敗しても、既に取得済みの正常なカタログを巻き戻さない", async () => {
    // 呼び出し回数はテストファイル内で共有されるため、このテスト内での増分だけを見る
    // （「同時にマウントされた複数の呼び出し元」テストと同じ方針）。
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
