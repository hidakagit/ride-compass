import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse, RoutePreferenceWeights } from "@/types/route";
import type { MapLayerId, MapLayerVisibility } from "@/components/Map/mapLayers";
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

// 改善計画T418: layerVisibility/onLayerToggle/hasDetailが新規必須propsになったための
// 既定値。個々のテストは必要な値だけ上書きする。
function baseLayerVisibility(): MapLayerVisibility {
  return {
    elevation: false,
    roadType: false,
    roadSurface: false,
    designation: false,
    tunnel: false,
    oneway: false,
    stopPoi: false,
    supplyPoi: false,
    accidents: false,
    route: false,
    precipitationNowcast: false,
    windVector: false,
    windAxis: false,
    gradientFill: false,
    gradientAxis: false,
    thunderNowcast: false,
    tornadoNowcast: false,
    liden: false,
  };
}

function baseNewProps() {
  return {
    layerVisibility: baseLayerVisibility(),
    onLayerToggle: vi.fn() as (id: MapLayerId, on: boolean) => void,
    hasDetail: false,
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
        {...baseNewProps()}
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
        {...baseNewProps()}
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
        {...baseNewProps()}
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
          {...baseNewProps()}
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

  // 改善計画T418: 軸ごとの「この条件で地図を色分け」トグル（renderMapColorToggle）。
  // 評価軸チップを地図UIから撤去したのに伴い、軸選択・重み設定と同じ行から地図色分けを
  // 起動できるようにした（docs/tasks/T418.md「やること」2.）。
  describe("軸ごとの地図色分けトグル（改善計画T418）", () => {
    it("専用の表示レイヤーを持つ軸（kind=ramp）は色分けトグルが押せ、layerVisibilityに応じたON/OFFをonLayerToggleへ伝える", async () => {
      const user = userEvent.setup();
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["car_stress"], { car_stress: "ramp" }));
      const onLayerToggle = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ car_stress: 0.3 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          onLayerToggle={onLayerToggle}
        />,
      );

      const toggle = await screen.findByRole("button", { name: "ラベル[car_stress]で地図を色分け表示" });
      expect(toggle).toHaveAttribute("aria-pressed", "false");

      await user.click(toggle);
      expect(onLayerToggle).toHaveBeenCalledWith("axis:car_stress", true);
    });

    it("専用の表示レイヤーを持たない軸（kind=none、風・勾配以外の未対応軸）は凡例チップに地図色分けアイコンが付かない", async () => {
      // 改善計画T423: 勾配（gradient）はgradientAxisという専用レイヤーを持つようになった
      // ため、この「地図表示非対応」ケースの例としては使えなくなった。wind/gradient
      // どちらでもない、まだ地図表示用のデータ取得経路が無い軸の例として架空のaxisIdを使う。
      // ユーザー要望（2026-08-31、凡例チップへの集約）で「地図表示なし」という文言表示は
      // 廃止し、非対応の軸はアイコンごと出さない方式へ変更した（凡例を圧迫しないため）。
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["no_map_layer_axis"], { no_map_layer_axis: "none" }));

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ no_map_layer_axis: 0.3 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
        />,
      );

      // findByRoleでモック済みカタログ（axis 1件のみ）が反映されるまで待つ
      // （フェッチ完了前は静的フォールバックカタログ[複数軸、地図色分け対応軸を含む]が
      // 一瞬使われ、absenceの確認をこのタイミングより前に行うと誤検知する）。
      // 凡例チップ1件が持つボタンは「トグル(色ドット+ラベル)」「(i)説明文」の2つだけ
      // （地図色分けアイコンが付かない）ことを確認する。
      const infoButton = await screen.findByRole("button", { name: "ラベル[no_map_layer_axis]の説明を表示" });
      const chip = infoButton.closest("span");
      expect(chip?.querySelectorAll("button")).toHaveLength(2);
      expect(chip?.querySelector('[aria-label*="で地図を色分け表示"]')).not.toBeInTheDocument();
    });

    it("風（wind）はsecondaryAxesに現れない特殊軸だが、windAxisレイヤーへの色分けトグルとして機能する", async () => {
      const user = userEvent.setup();
      // 改善計画T447（2026-08-31訂正）: windはbackendのAXIS_DEFINITIONS上
      // category="動的"・show_map_icon=trueで公開される（secondaryAxes.tsが
      // show_map_iconではなくcategoryで除外する、axis_definitions_snapshot.json参照。
      // 旧コメントは主張が逆だった——詳細はsecondaryAxes.tsのコメント参照）。
      vi.mocked(getAxisCatalog).mockResolvedValue({
        axes: [
          {
            axis_id: "wind",
            label: "風",
            description: "向かい風が弱いほど易しい",
            category: "動的",
            default_weight: 0.26,
            display: { kind: "none", label: "風", category: "weather", tile_inputs: [], thresholds: [], unit: "", note: "" },
            primary_attribute_ids: [],
            icon_id: null,
            chip_label: null,
            panel_hint: null,
            show_map_icon: true,
            shape: { kind: "breakpoint_linear", terms: [{ material: "wind_penalty", weight: 1.0, required: true }], preprocess: "identity", breakpoints: [[0, 0], [10, 100]] },
            display_thresholds_override: null,
            display_band_labels_override: null,
            dedicated_way_value_layer: true,
            map_value_kind: "difficulty",
            map_value_unit: "",
          },
        ],
        material_runtime_scales: {},
      });
      const onLayerToggle = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ wind: 0.26 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          onLayerToggle={onLayerToggle}
        />,
      );

      const toggle = await screen.findByRole("button", { name: "風で地図を色分け表示" });
      await user.click(toggle);
      expect(onLayerToggle).toHaveBeenCalledWith("windAxis", true);
    });

    it("ルート確定後（hasDetail=true）は風の色分けトグルが非対応の案内に切り替わる", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue({
        axes: [
          {
            axis_id: "wind",
            label: "風",
            description: "向かい風が弱いほど易しい",
            category: "推定",
            default_weight: 0.26,
            display: { kind: "none", label: "風", category: "weather", tile_inputs: [], thresholds: [], unit: "", note: "" },
            primary_attribute_ids: [],
            icon_id: null,
            chip_label: null,
            panel_hint: null,
            show_map_icon: false,
            shape: { kind: "breakpoint_linear", terms: [{ material: "wind_penalty", weight: 1.0, required: true }], preprocess: "identity", breakpoints: [[0, 0], [10, 100]] },
            display_thresholds_override: null,
            display_band_labels_override: null,
            dedicated_way_value_layer: true,
            map_value_kind: "difficulty",
            map_value_unit: "",
          },
        ],
        material_runtime_scales: {},
      });

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ wind: 0.26 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          hasDetail
        />,
      );

      // ユーザー要望（2026-08-31、凡例チップへの集約）で「地図表示なし」の文言表示は
      // 廃止し、案内文はtitle/aria-label付きの無効化アイコンへ置き換わった。
      await waitFor(() =>
        expect(
          screen.getByTitle('ルート確定後は「地図の色分け」の「風」で確認できます'),
        ).toBeInTheDocument(),
      );
      expect(screen.queryByRole("button", { name: "風で地図を色分け表示" })).not.toBeInTheDocument();
    });

    it("勾配（gradient）はsecondaryAxesに現れない特殊軸だが、gradientAxisレイヤーへの色分けトグルとして機能する（改善計画T423）", async () => {
      const user = userEvent.setup();
      vi.mocked(getAxisCatalog).mockResolvedValue(
        catalogResponse(["gradient"], { gradient: "none" }, { gradient: true }),
      );
      const onLayerToggle = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ gradient: 0.15 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          onLayerToggle={onLayerToggle}
        />,
      );

      const toggle = await screen.findByRole("button", { name: "ラベル[gradient]で地図を色分け表示" });
      await user.click(toggle);
      expect(onLayerToggle).toHaveBeenCalledWith("gradientAxis", true);
    });

    it("ルート確定後（hasDetail=true）は勾配の色分けトグルが非対応の案内に切り替わる（改善計画T423）", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue(
        catalogResponse(["gradient"], { gradient: "none" }, { gradient: true }),
      );

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ gradient: 0.15 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          hasDetail
        />,
      );

      // ユーザー要望（2026-08-31、凡例チップへの集約）で「地図表示なし」の文言表示は
      // 廃止し、案内文はtitle/aria-label付きの無効化アイコンへ置き換わった。
      // 改善計画T440: 案内文のラベルはハードコードした「勾配」ではなく、軸データ自身の
      // labelをそのまま使う（catalogResponseのテスト用ラベル「ラベル[gradient]」）。
      await waitFor(() =>
        expect(
          screen.getByTitle('ルート確定後は「地図の色分け」の「ラベル[gradient]」で確認できます'),
        ).toBeInTheDocument(),
      );
      expect(screen.queryByRole("button", { name: "ラベル[gradient]で地図を色分け表示" })).not.toBeInTheDocument();
    });
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
          {...baseNewProps()}
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
          {...baseNewProps()}
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
          {...baseNewProps()}
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
