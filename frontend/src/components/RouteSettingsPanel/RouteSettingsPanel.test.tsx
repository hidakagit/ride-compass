import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";
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
import axisCatalogStatic from "@/types/generated/axis-catalog.json";

function catalogResponse(axisIds: string[]): AxisCatalogResponse {
  return {
    axes: axisIds.map((axisId) => ({
      axis_id: axisId,
      label: `ラベル[${axisId}]`,
      description: "",
      category: "観測",
      default_weight: 0.1,
    })),
  };
}

describe("RouteSettingsPanel", () => {
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
});
