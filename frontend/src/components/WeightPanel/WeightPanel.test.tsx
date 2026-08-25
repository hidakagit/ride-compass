import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import WeightPanel, { DEFAULT_SCORING_WEIGHTS } from "./WeightPanel";

const TITLE = "おすすめ度の重み[候補一覧内の相対評価、次回のルート生成に反映]";

describe("WeightPanel", () => {
  it("上書き無効でも展開すれば既定値の入力欄を表示できる", async () => {
    const user = userEvent.setup();
    render(
      <WeightPanel
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={DEFAULT_SCORING_WEIGHTS}
        onScoringWeightsChange={vi.fn()}
      />,
    );

    await user.click(screen.getByText(TITLE));

    expect(screen.getAllByRole("spinbutton")).toHaveLength(4);
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
      />,
    );

    await user.click(screen.getByRole("button", { name: "おすすめ度の重みを上書き" }));

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
      />,
    );

    await user.click(screen.getByText(TITLE));
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
      />,
    );

    await user.click(screen.getByText(TITLE));

    const infoButton = screen.getByRole("button", { name: "距離の合わせ込みの説明を表示" });
    expect(screen.queryByText(/指定距離との差の小ささ/)).not.toBeInTheDocument();

    await user.click(infoButton);
    expect(screen.getByText(/指定距離との差の小ささ/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "距離の合わせ込みの説明を隠す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "距離の合わせ込みの説明を隠す" }));
    expect(screen.queryByText(/指定距離との差の小ささ/)).not.toBeInTheDocument();
  });

  it("既定値に戻すボタンでscoringWeightsを既定値へ戻す", async () => {
    const user = userEvent.setup();
    const onScoringChange = vi.fn();
    render(
      <WeightPanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        scoringWeights={{ distance_weight: 0.9, elevation_weight: 0.9, wind_weight: 0.9, road_weight: 0.9 }}
        onScoringWeightsChange={onScoringChange}
      />,
    );

    await user.click(screen.getByText(TITLE));
    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onScoringChange).toHaveBeenCalledWith(DEFAULT_SCORING_WEIGHTS);
  });
});
