import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse, RoutePreferenceWeights } from "@/types/route";
import RouteSettingsPanel, { DEFAULT_HARD_FILTERS } from "./RouteSettingsPanel";

// 改善計画T302: unpublishでカタログから軸が消えた場合、RouteSettingsPanelが
// routePreferenceから対応するキーを自動で取り除く（自己修復）ことの回帰テスト。
// これが無いと、unpublish直後に旧設定を保持したブラウザで次のルート生成が
// RoutePreferenceWeightsのキー完全一致検証（backend/app/api/routers/routes.py）で
// 422になる（docs/decisions/t221-axis-registry.md「Stage D拡張3」参照）。
vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { getAxisCatalog } from "@/services/axisCatalogApi";
import { __resetAxisCatalogStoreForTests } from "@/hooks/useAxisCatalog";
import axisCatalogStatic from "@/types/generated/axis-catalog.json";

// 改善計画T418: 軸ごとの「地図で色分け」トグル（renderMapColorToggle）検証用に、
// display.kindを呼び出し側で選べるよう拡張した（従来は全軸kind="none"固定だった）。
// 改善計画T440: dedicatedWayValueLayerByAxisIdも同様に呼び出し側で選べるようにした
// （専用way_id配信層を持つ軸[wind/gradient]のテストが、この軸データを直接指定できる
// ようにするため——axis_idのハードコード比較ではなく軸データで判定する設計に合わせた）。
function catalogResponse(
  axisIds: string[],
  kindByAxisId: Record<string, "none" | "ramp"> = {},
  dedicatedWayValueLayerByAxisId: Record<string, boolean> = {},
): AxisCatalogResponse {
  return {
    axes: axisIds.map((axisId) => {
      const kind = kindByAxisId[axisId] ?? "none";
      return {
        axis_id: axisId,
        label: `ラベル[${axisId}]`,
        description: "",
        category: "観測",
        default_weight: 0.1,
        // 改善計画T308: GET /api/axis-catalogのレスポンスへdisplay/primary_attribute_idsが
        // 必須フィールドとして追加された。改善計画T310でicon_id/chip_label/panel_hintも
        // 同様に必須（値はnull許容）となった。改善計画T318でshow_map_icon（真偽値、
        // null不可）も必須フィールドに加わった。このテストはどれも内容を検証しないため
        // kind="none"・空配列・null・trueで済ませる（kind="ramp"のtile_inputs/thresholdsは
        // renderMapColorToggleがlayerIdの有無しか見ないため空でよい）。
        display: {
          kind,
          label: `ラベル[${axisId}]`,
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
        primary_attribute_ids: [],
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        show_map_icon: true,
        shape: { kind: "breakpoint_linear", terms: [{ material: "gradient_percent", weight: 1.0, required: true }], preprocess: "identity", breakpoints: [[0, 0], [10, 100]] },
        display_thresholds_override: null,
        display_band_labels_override: null,
        dedicated_way_value_layer: dedicatedWayValueLayerByAxisId[axisId] ?? false,
        map_value_kind: "difficulty",
        map_value_unit: "",
      };
    }),
    // 改善計画T404: material_runtime_scalesはAxisCatalogResponseの必須フィールド
    // （既定{}だがopenapi-typescriptはdefault付きフィールドをoptionalにしない）。
    material_runtime_scales: {},
  };
}

describe("RouteSettingsPanel", () => {
  // 改善計画T527: useAxisCatalogのフェッチ結果はモジュールレベルの共有ストアのため、
  // 前のテストで解決したカタログが次のテストの初期表示へ持ち越されないようリセットする。
  beforeEach(() => {
    __resetAxisCatalogStoreForTests();
  });

  it("カタログから消えた軸（unpublish後）のキーをroutePreferenceから取り除く", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        // "night"は下書きへ戻った(unpublishされた)想定の古いキー。
        routePreference={{ gradient: 0.5, surface_q: 0.3, night: 0.2 }}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
      />,
    );

    await waitFor(() => expect(onRoutePreferenceChange).toHaveBeenCalled());

    const synced = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
    expect(synced).toEqual({ gradient: 0.5, surface_q: 0.3 });
  });

  it("カタログに新しく現れた軸の既定重みをroutePreferenceへ補う", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        routePreference={{ gradient: 0.5 }}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
      />,
    );

    await waitFor(() => expect(onRoutePreferenceChange).toHaveBeenCalled());

    const synced = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
    expect(synced).toEqual({ gradient: 0.5, surface_q: 0.1 });
  });

  it("routePreferenceがカタログと既に一致している場合は呼び出さない", async () => {
    // マウント直後はフェッチ完了までの一瞬、静的フォールバックカタログ
    // （axis-catalog.json、useAxisCatalog.tsのFALLBACK_CATALOG）がそのまま使われる
    // ため、この初期状態とも一致させておかないと「フェッチ前の一瞬だけ差分が
    // あるから呼ばれる」という別の要因で誤検知する。フォールバックと同じ内容を
    // 返すモックにしておくことで、フェッチ前後どちらの時点でも一致した状態を保つ。
    const staticDefaults = axisCatalogStatic.preference_defaults as Record<string, number>;
    vi.mocked(getAxisCatalog).mockResolvedValue(
      catalogResponse(Object.keys(staticDefaults)),
    );
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        routePreference={staticDefaults}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
      />,
    );

    // フェッチが解決してeffectが走り切るまで待つ（呼ばれないことの確認のため一呼吸置く）。
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(onRoutePreferenceChange).not.toHaveBeenCalled();
  });

  // 改善計画T471: lastWeights（チェックを外した軸の重みを覚えておく内部state）は
  // マウント時点のcatalog.defaultWeights（フェッチ完了前は静的フォールバック値）で
  // 初期化される。以前はフェッチ完了後にcatalog.defaultWeightsが実際の値へ更新されても
  // 追従せず、一度チェックを外して戻すと古いフォールバック値へ復元されていた。
  it("フェッチ完了で既定重みが変わった場合、チェックを外して戻すと新しい既定値へ復元される（古いフォールバック値ではない）", async () => {
    const user = userEvent.setup();
    // 静的フォールバック（axis-catalog.json: preference_defaults.gradient）とは異なる値を
    // 実行時フェッチの応答として返し、フェッチ前後で既定重みが変わる状況を再現する。
    const response = catalogResponse(["gradient"]);
    response.axes[0].default_weight = 0.42;
    vi.mocked(getAxisCatalog).mockResolvedValue(response);
    const onRoutePreferenceChange = vi.fn();

    function Wrapper() {
      const [routePreference, setRoutePreference] = useState<RoutePreferenceWeights>({ gradient: 0.5 });
      return (
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={routePreference}
          onRoutePreferenceChange={(next) => {
            onRoutePreferenceChange(next);
            setRoutePreference(next);
          }}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
        />
      );
    }

    render(<Wrapper />);

    // フェッチ完了（default_weight=0.42への追従）を待つ。
    await waitFor(() => expect(getAxisCatalog).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));

    // ユーザー要望（2026-08-31、凡例チップへの集約）でチェックボックスは廃止され、
    // 凡例チップのトグルボタン（色ドット+ラベル、aria-labelに有効/無効の状態を含む）に
    // 置き換わった。状態が変わるとaria-labelも変わるため、クリックのたびに再取得する。
    await user.click(screen.getByRole("button", { name: "ラベル[gradient]を無効にする" })); // チェックを外す(weight=0)
    await user.click(screen.getByRole("button", { name: "ラベル[gradient]を有効にする" })); // 再度チェックする(lastWeightsから復元)

    const restored = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
    expect(restored.gradient).toBe(0.42);
  });


  // ユーザー要望（2026-08-31、「複数要素を足し合わせて1にするのを直感的に省スペース設定
  // できるUIはないか」）: 重み配分バー（帯グラフ）の境界を操作すると、隣接する2軸間でだけ
  // 重みが移動し、合計（2軸ぶんの和）は変わらないことの回帰テスト。実際のポインタドラッグは
  // happy-domがレイアウト（getBoundingClientRect）を計算しないため単体テストで再現できず、
  // Browserペインでの実機確認で検証済み（docs/tasks/T495.md参照）。ここでは
  // getBoundingClientRectに依存しないキーボード操作（矢印キー）経路で、隣接軸ペアの
  // 重み移動ロジック（clampBoundaryDrag）自体を検証する。
  describe("重み配分バー（帯グラフ）の境界操作", () => {
    it("境界をArrowRightキーで操作すると隣接する2軸の重みだけがWEIGHT_STEP分移動し、2軸の合計は変わらない", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
      const onRoutePreferenceChange = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ gradient: 0.5, surface_q: 0.3 }}
          onRoutePreferenceChange={onRoutePreferenceChange}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
        />,
      );

      const handle = await screen.findByRole("slider", { name: "ラベル[gradient]とラベル[surface_q]の配分" });
      fireEvent.keyDown(handle, { key: "ArrowRight" });

      const updated = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
      expect(updated.gradient).toBeCloseTo(0.51);
      expect(updated.surface_q).toBeCloseTo(0.29);
    });

    it("境界をArrowLeftキーで操作すると逆方向に移動する", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
      const onRoutePreferenceChange = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ gradient: 0.5, surface_q: 0.3 }}
          onRoutePreferenceChange={onRoutePreferenceChange}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
        />,
      );

      const handle = await screen.findByRole("slider", { name: "ラベル[gradient]とラベル[surface_q]の配分" });
      fireEvent.keyDown(handle, { key: "ArrowLeft" });

      const updated = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
      expect(updated.gradient).toBeCloseTo(0.49);
      expect(updated.surface_q).toBeCloseTo(0.31);
    });

    it("上限(0.6)に達している軸へさらに寄せようとしても超えない", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
      const onRoutePreferenceChange = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ gradient: 0.6, surface_q: 0.2 }}
          onRoutePreferenceChange={onRoutePreferenceChange}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
        />,
      );

      const handle = await screen.findByRole("slider", { name: "ラベル[gradient]とラベル[surface_q]の配分" });
      // フェッチ完了前は静的フォールバックカタログ（axis-catalog.json）が一瞬使われ、
      // routePreferenceに無いキーを補うsyncRoutePreferenceKeys由来の1回がここで既に
      // 呼ばれている（「フェッチ完了で既定重みが変わった場合…」テストの前提と同じ）。
      // その呼び出し回数を基準にし、キー操作の結果「新規呼び出しが増えないこと」を見る。
      await waitFor(() => expect(getAxisCatalog).toHaveBeenCalled());
      await new Promise((resolve) => setTimeout(resolve, 0));
      const callCountBeforeKeyDown = onRoutePreferenceChange.mock.calls.length;

      fireEvent.keyDown(handle, { key: "ArrowRight" });

      expect(onRoutePreferenceChange).toHaveBeenCalledTimes(callCountBeforeKeyDown);
    });
  });
});
