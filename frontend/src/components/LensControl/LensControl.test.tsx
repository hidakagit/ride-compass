import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import LensControl, { type LensOption } from "./LensControl";

const OPTIONS: LensOption[] = [
  { id: "wind", label: "風", color: "#111", unused: false, routeOnly: false },
  { id: "car_stress", label: "車ストレス", color: "#222", unused: false, routeOnly: false },
  { id: "night", label: "夜間", color: "#333", unused: true, routeOnly: true },
];

const LEGEND = [
  { key: "a", label: "0〜50", color: "#0f0", filter: [] },
  { key: "b", label: "50〜100", color: "#f00", filter: [] },
];

function baseProps(overrides: Partial<Parameters<typeof LensControl>[0]> = {}) {
  return {
    lens: "difficulty",
    onLensChange: vi.fn(),
    axisOptions: OPTIONS,
    legend: LEGEND,
    keepAfterRoute: true,
    onKeepAfterRouteChange: vi.fn(),
    hasDetail: false,
    ...overrides,
  };
}

describe("LensControl", () => {
  it("ピルは現在のレンズ名を示し、タップで単一選択の一覧（なし/総合難易度/使用中/未使用）が開く", async () => {
    const user = userEvent.setup();
    render(<LensControl {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "レンズ: 総合難易度（タップで変更）" }));

    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(["なし", "総合難易度", "風", "車ストレス", "夜間未使用ルート後のみ"]);
    expect(screen.getByRole("radio", { name: /総合難易度/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("評価に使用中")).toBeInTheDocument();
    expect(screen.getAllByText("未使用")).toHaveLength(2); // グループ見出し＋バッジ
  });

  it("選択するとonLensChangeが呼ばれ、ポップオーバーが閉じる", async () => {
    const user = userEvent.setup();
    const onLensChange = vi.fn();
    render(<LensControl {...baseProps({ onLensChange })} />);

    await user.click(screen.getByRole("button", { name: /レンズ:/ }));
    await user.click(screen.getByRole("radio", { name: /^風$/ }));

    expect(onLensChange).toHaveBeenCalledWith("wind");
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });

  it("重み0の軸も選べる（未使用バッジ付き）。ルート後は「ルート後のみ」バッジを出さない", async () => {
    const user = userEvent.setup();
    const onLensChange = vi.fn();
    render(<LensControl {...baseProps({ onLensChange, hasDetail: true })} />);

    await user.click(screen.getByRole("button", { name: /レンズ:/ }));
    expect(screen.queryByText("ルート後のみ")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /夜間/ }));

    expect(onLensChange).toHaveBeenCalledWith("night");
  });

  it("「ルート後も周囲の道路を薄く塗る」の切替がonKeepAfterRouteChangeへ届く", async () => {
    const user = userEvent.setup();
    const onKeepAfterRouteChange = vi.fn();
    render(<LensControl {...baseProps({ onKeepAfterRouteChange })} />);

    await user.click(screen.getByRole("button", { name: /レンズ:/ }));
    await user.click(screen.getByRole("checkbox", { name: "ルート後も周囲の道路を薄く塗る" }));

    expect(onKeepAfterRouteChange).toHaveBeenCalledWith(false);
  });

  it("ルート後は凡例の段階を非表示にできる（hiddenLegendKeys/onToggleLegendKeyがあるときだけチェックボックス）", async () => {
    const user = userEvent.setup();
    const onToggleLegendKey = vi.fn();
    render(<LensControl {...baseProps({ hasDetail: true, hiddenLegendKeys: [], onToggleLegendKey })} />);

    await user.click(screen.getByRole("button", { name: /レンズ:/ }));
    await user.click(screen.getByRole("checkbox", { name: /0〜50/ }));

    expect(onToggleLegendKey).toHaveBeenCalledWith("a");
  });

  it("レンズ「なし」でもピルは残る（入口が消えない）", () => {
    render(<LensControl {...baseProps({ lens: "none", legend: [] })} />);

    expect(screen.getByRole("button", { name: "レンズ: なし（タップで変更）" })).toBeInTheDocument();
  });

  it("dataStatus未指定（正常時）はピルにtitleを付けない", () => {
    render(<LensControl {...baseProps({ lens: "wind" })} />);

    expect(screen.getByRole("button", { name: /レンズ:/ })).not.toHaveAttribute("title");
  });

  it("dataStatus='error'のとき、専用配信軸のフェッチ失敗をピルのtitleで示す", () => {
    render(<LensControl {...baseProps({ lens: "wind", dataStatus: "error" })} />);

    expect(screen.getByRole("button", { name: /レンズ:/ })).toHaveAttribute(
      "title",
      "データの取得に失敗しました。しばらくしてから再読み込みしてください"
    );
  });
});
