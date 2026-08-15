import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import WeightPanel, { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "./WeightPanel";

describe("WeightPanel", () => {
  it("上書き無効時は重み入力欄を表示しない", () => {
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

    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("上書き有効時はscoring 4値+preference 3値の入力欄を表示する", () => {
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

    expect(screen.getAllByRole("spinbutton")).toHaveLength(7);
  });

  it("トグルをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
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

    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
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
        routePreference={{ elevation_weight: 0.9, road_weight: 0.9, wind_weight: 0.9 }}
        onRoutePreferenceChange={onPreferenceChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onScoringChange).toHaveBeenCalledWith(DEFAULT_SCORING_WEIGHTS);
    expect(onPreferenceChange).toHaveBeenCalledWith(DEFAULT_ROUTE_PREFERENCE);
  });
});
