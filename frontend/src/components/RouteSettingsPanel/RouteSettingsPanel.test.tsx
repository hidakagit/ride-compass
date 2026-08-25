import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
      // 改善計画T308: GET /api/axis-catalogのレスポンスへdisplay/primary_attribute_idsが
      // 必須フィールドとして追加された。改善計画T310でicon_id/chip_label/panel_hint/
      // proxy_hintも同様に必須（値はnull許容）となった。このテストはどれも内容を検証
      // しないためkind="none"・空配列・nullで済ませる。
      display: { kind: "none", label: `ラベル[${axisId}]`, category: "trafficSafety", unit: "", note: "" },
      primary_attribute_ids: [],
      icon_id: null,
      chip_label: null,
      panel_hint: null,
      proxy_hint: null,
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

  // 改善計画T313回帰テスト: 「バランス以外のルート設定を選択すると、重み配分がMAXに
  // ならない」不具合。以前はプリセットが言及しない軸をcatalog.defaultWeights（非ゼロ）で
  // 補っていたため、軸スタジオ経由でプリセット未対応の軸（既存7軸以外）が公開されると、
  // 非バランスプリセットの重み配分にその軸の既定重みが黙って混入し、対象軸の相対比率が
  // 意図した値まで上がらなくなっていた。
  it("非バランスプリセット適用時、プリセットが言及しない軸は0になる（catalog既定重みで薄まらない）", async () => {
    // 既存7軸に加え、プリセットが一切知らない軸スタジオ発の公開軸`new_axis`を含むカタログ。
    vi.mocked(getAxisCatalog).mockResolvedValue(
      catalogResponse([
        "gradient", "surface_q", "stop_density", "night", "car_stress", "accident", "wind", "new_axis",
      ]),
    );
    const user = userEvent.setup();
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        routePreference={{}}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
      />,
    );

    // プリセットボタン自体は静的フォールバックカタログの段階から常に描画されるため、
    // 実カタログ（new_axisを含む8軸）への切り替わりを軸一覧の描画で待ってからクリックする。
    await waitFor(() => expect(screen.getByText("ラベル[new_axis]")).toBeInTheDocument());
    await user.click(screen.getByText("自転車専用道を優先"));

    const applied = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
    expect(applied).toEqual({
      gradient: 0.1, surface_q: 0.12, stop_density: 0.22, night: 0.0,
      car_stress: 0.45, accident: 0.08, wind: 0.03, new_axis: 0,
    });
  });
});
