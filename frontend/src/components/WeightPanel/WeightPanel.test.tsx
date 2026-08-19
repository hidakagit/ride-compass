import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import WeightPanel, { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "./WeightPanel";

const TITLE = "評価重み[次回のルート生成に反映]";

describe("WeightPanel", () => {
  it("上書き無効でも展開すれば既定値の入力欄を表示できる", async () => {
    const user = userEvent.setup();
    render(
      <WeightPanel
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={vi.fn()}
        routePreference={DEFAULT_ROUTE_PREFERENCE}
        onRoutePreferenceChange={vi.fn()}
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByText("おすすめ度の重み[候補一覧内の相対評価]"));

    expect(screen.getAllByRole("spinbutton").length).toBeGreaterThan(0);
  });

  it("上書き有効時はscoring 4値+preference 7値の入力欄を表示する", async () => {
    // 改善計画: 研究の中身も折りたたみ式に統一（MapLayersPanelのレイヤー折りたたみと
    // 同じ構成）。各グループはdetailsでデフォルト全閉のため、中の入力欄は開くまで
    // アクセシビリティツリー上に現れない（jsdomもブラウザと同じ挙動）。
    const user = userEvent.setup();
    render(
      <WeightPanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={vi.fn()}
        routePreference={DEFAULT_ROUTE_PREFERENCE}
        onRoutePreferenceChange={vi.fn()}
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByText("おすすめ度の重み[候補一覧内の相対評価]"));
    await user.click(screen.getByText("区間難易度の重み[絶対評価]"));

    expect(screen.getAllByRole("spinbutton")).toHaveLength(11);
  });

  it("上書きチップをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <WeightPanel
        overrideEnabled={false}
        onOverrideEnabledChange={onChange}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={vi.fn()}
        routePreference={DEFAULT_ROUTE_PREFERENCE}
        onRoutePreferenceChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "評価重みを上書き" }));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("上書き無効時に入力欄を変更すると上書きが自動でONになる", async () => {
    const user = userEvent.setup();
    const onOverrideEnabledChange = vi.fn();
    const onScoringWeightsChange = vi.fn();
    render(
      <WeightPanel
        overrideEnabled={false}
        onOverrideEnabledChange={onOverrideEnabledChange}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={onScoringWeightsChange}
        routePreference={DEFAULT_ROUTE_PREFERENCE}
        onRoutePreferenceChange={vi.fn()}
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByText("おすすめ度の重み[候補一覧内の相対評価]"));
    const input = screen.getAllByRole("spinbutton")[0];
    fireEvent.change(input, { target: { value: "0.5" } });

    expect(onOverrideEnabledChange).toHaveBeenCalledWith(true);
    expect(onScoringWeightsChange).toHaveBeenCalled();
  });

  it("情報アイコンをクリックすると軸の説明が表示され、もう一度押すと隠れる", async () => {
    const user = userEvent.setup();
    render(
      <WeightPanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={vi.fn()}
        routePreference={DEFAULT_ROUTE_PREFERENCE}
        onRoutePreferenceChange={vi.fn()}
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByText("区間難易度の重み[絶対評価]"));

    const infoButton = screen.getByRole("button", { name: "車の圧迫感の説明を表示" });
    expect(screen.queryByText(/信号や交差点の頻度は含まない/)).not.toBeInTheDocument();

    await user.click(infoButton);
    expect(screen.getByText(/信号や交差点の頻度は含まない/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "車の圧迫感の説明を隠す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "車の圧迫感の説明を隠す" }));
    expect(screen.queryByText(/信号や交差点の頻度は含まない/)).not.toBeInTheDocument();
  });

  it("既定値に戻すボタンでscoring/preferenceともに既定値へ戻す", async () => {
    const user = userEvent.setup();
    const onScoringChange = vi.fn();
    const onPreferenceChange = vi.fn();
    render(
      <WeightPanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={{ distance_weight: 0.9, elevation_weight: 0.9, wind_weight: 0.9, road_weight: 0.9 }}
        onScoringWeightsChange={onScoringChange}
        routePreference={{
          elevation_weight: 0.9, road_weight: 0.9, wind_weight: 0.9, stop_weight: 0.9,
          car_stress_weight: 0.9, accident_weight: 0.9,
          night_weight: 0.9,
        }}
        onRoutePreferenceChange={onPreferenceChange}
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onScoringChange).toHaveBeenCalledWith(DEFAULT_SCORING_WEIGHTS);
    expect(onPreferenceChange).toHaveBeenCalledWith(DEFAULT_ROUTE_PREFERENCE);
  });

  // 改善計画: 研究タブを2次要素ごとに整理。区間難易度の重み（PREFERENCE_FIELDS）の
  // 各行の直下へ、その軸固有の内容（page.tsx側が組み立てるレシピパネル等）を
  // 差し込める汎用の枠（renderPreferenceFieldExtra）を検証する。
  it("renderPreferenceFieldExtraは対象のweightKeyの行にだけ差し込まれる", async () => {
    const user = userEvent.setup();
    render(
      <WeightPanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={vi.fn()}
        routePreference={DEFAULT_ROUTE_PREFERENCE}
        onRoutePreferenceChange={vi.fn()}
        renderPreferenceFieldExtra={(weightKey) =>
          weightKey === "car_stress_weight" ? <p>車ストレスのレシピをここに差し込む</p> : null
        }
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByText("区間難易度の重み[絶対評価]"));

    expect(screen.getByText("車ストレスのレシピをここに差し込む")).toBeInTheDocument();
  });
});
