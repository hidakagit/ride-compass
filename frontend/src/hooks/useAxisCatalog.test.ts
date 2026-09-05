import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";

// 改善計画T308: useAxisCatalogがrampAxes/axisLabels/secondaryAxesを実行時APIから
// 導出することの回帰テスト。RouteSettingsPanel.test.tsxと同じモック方針。
vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { getAxisCatalog } from "@/services/axisCatalogApi";
import { __resetAxisCatalogStoreForTests, useAxisCatalog } from "./useAxisCatalog";

// 改善計画T527: フェッチ結果をモジュールレベルの共有ストアへ変更したため、前のテストの
// 解決済みカタログが次のテストの初期値へ持ち越されないよう、テストごとにリセットする。
beforeEach(() => {
  __resetAxisCatalogStoreForTests();
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
        display: { kind: "none", label: "舗装質", category: "trafficSafety", unit: "", note: "" },
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
        map_value_unit: "",
      },
      // 軸スタジオで公開されたばかりの新規GUI軸（複数材料の重み付き結合、kind=ramp）。
      // ビルド時静的axis-catalog.jsonには存在しない、実行時APIだけが返す想定。
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
          unit: "",
          note: "",
        },
        primary_attribute_ids: ["lanes"],
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        show_map_icon: true,
        shape: { kind: "breakpoint_linear", terms: [{ material: "lanes_count", weight: 1.0, required: true }], preprocess: "identity", breakpoints: [[0, 0], [10, 100]] },
        display_thresholds_override: null,
        display_band_labels_override: null,
        dedicated_way_value_layer: false,
        map_value_kind: "difficulty",
        map_value_unit: "",
      },
    ],
    // 改善計画T404: material_runtime_scalesはAxisCatalogResponseの必須フィールド
    // （既定{}だがopenapi-typescriptはdefault付きフィールドをoptionalにしない）。
    material_runtime_scales: {},
  };
}

describe("useAxisCatalog（改善計画T308: rampAxes/axisLabels/secondaryAxesの実行時フェッチ）", () => {
  it("実行時フェッチが完了すると、GUI公開軸を含むrampAxesを返す", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse());

    const { result } = renderHook(() => useAxisCatalog());

    await waitFor(() => {
      expect(result.current.rampAxes.some((axis) => axis.axisId === "gui_published_axis")).toBe(true);
    });

    const guiAxis = result.current.rampAxes.find((axis) => axis.axisId === "gui_published_axis")!;
    expect(guiAxis.tileInputs).toEqual([
      { property: "lanes_count", weight: 1.0, boolean: false, trueValue: 0, falseValue: 0, hasUnknownFallback: false, categories: undefined, breakpoints: undefined },
    ]);
    expect(guiAxis.thresholds).toEqual([10.0]);
    // kind=noneのsurface_qはrampAxesには含まれないが、axisLabels/secondaryAxesには含まれる。
    expect(result.current.rampAxes.some((axis) => axis.axisId === "surface_q")).toBe(false);
    expect(result.current.axisLabels.gui_published_axis).toBe("GUI公開軸テスト");
    expect(result.current.axisLabels.surface_q).toBe("舗装質");
    const guiSecondaryAxis = result.current.secondaryAxes.find((axis) => axis.axisId === "gui_published_axis");
    expect(guiSecondaryAxis?.primaryAttributeIds).toEqual(["lanes"]);
  });

  it("改善計画T318フォローアップ: 全軸非公開でaxesが0件のレスポンスは、静的フォールバックへ戻さずそのまま空を返す", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue({ axes: [], material_runtime_scales: {} });

    const { result } = renderHook(() => useAxisCatalog());

    await waitFor(() => expect(result.current.axes).toEqual([]));
    expect(result.current.rampAxes).toEqual([]);
    // windは軸スタジオのレジストリ（AXIS_DEFINITIONS）とは別枠の構造的な特別扱い
    // （axisLayers.ts: axisLabelsFromCatalogAxes、専用の動的気象UIを別に持つため
    // 元々map表示レジストリに未登録）で、公開軸が0件でも変わらず残る想定どおりの挙動。
    expect(result.current.axisLabels).toEqual({ wind: "風" });
    expect(result.current.secondaryAxes).toEqual([]);
    expect(result.current.defaultWeights).toEqual({});
  });

  it("フェッチ失敗時は静的フォールバック（既存7軸）のrampAxesを返す", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useAxisCatalog());

    // フォールバックは初期値としてすでにセットされているため、フェッチが失敗して
    // 何も変わらないことを確認する（catchブロックが状態を書き換えない）。
    await waitFor(() => expect(vi.mocked(getAxisCatalog)).toHaveBeenCalled());
    expect(result.current.rampAxes.length).toBeGreaterThan(0);
    expect(result.current.rampAxes.every((axis) => axis.axisId !== "gui_published_axis")).toBe(true);
  });

  it("コードレビュー指摘の修正確認: 同時にマウントされた複数の呼び出し元は1回のフェッチを共有する", async () => {
    // page.tsx・RouteSettingsPanel.tsxが同時にuseAxisCatalog()を呼ぶ初回描画のシナリオ
    // （以前は呼び出し元の数だけGET /api/axis-catalogが同時に飛んでいた）。
    // 呼び出し回数はvi.mocked(getAxisCatalog)がテストファイル内で共有される（このテスト単体
    // では自動リセットされない）ため、このテスト内での増分だけを見る。
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse());
    const callsBefore = vi.mocked(getAxisCatalog).mock.calls.length;

    const first = renderHook(() => useAxisCatalog());
    const second = renderHook(() => useAxisCatalog());

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
    const first = renderHook(() => useAxisCatalog());
    await waitFor(() => expect(first.result.current.loaded).toBe(true));
    expect(first.result.current.axes).toHaveLength(2);

    // 軸スタジオでgui_published_axisが非公開になり、以後のフェッチは1軸だけ返す想定。
    vi.mocked(getAxisCatalog).mockResolvedValueOnce({
      axes: [catalogResponse().axes[0]],
      material_runtime_scales: {},
    });
    const second = renderHook(() => useAxisCatalog());

    await waitFor(() => expect(second.result.current.axes).toHaveLength(1));
    // firstは自分では再フェッチしていないが、共有ストア経由で最新の1軸へ追従する。
    expect(first.result.current.axes).toHaveLength(1);
    expect(first.result.current.axes).toBe(second.result.current.axes);
  });

  it("改善計画T527: 後発の呼び出し元の再フェッチが失敗しても、既に取得済みの正常なカタログを巻き戻さない", async () => {
    // 呼び出し回数はテストファイル内で共有されるため、このテスト内での増分だけを見る
    // （「同時にマウントされた複数の呼び出し元」テストと同じ方針）。
    vi.mocked(getAxisCatalog).mockResolvedValueOnce(catalogResponse());
    const first = renderHook(() => useAxisCatalog());
    await waitFor(() => expect(first.result.current.loaded).toBe(true));
    const callsBefore = vi.mocked(getAxisCatalog).mock.calls.length;

    vi.mocked(getAxisCatalog).mockRejectedValueOnce(new Error("network error"));
    const second = renderHook(() => useAxisCatalog());
    await waitFor(() =>
      expect(vi.mocked(getAxisCatalog).mock.calls.length - callsBefore).toBe(1),
    );

    // secondの再フェッチが失敗しても、firstが既に取得していた2軸のカタログのまま
    // （静的フォールバックの7軸へ巻き戻らない）。
    expect(first.result.current.loaded).toBe(true);
    expect(first.result.current.axes).toHaveLength(2);
    expect(second.result.current.axes).toHaveLength(2);
  });
});
