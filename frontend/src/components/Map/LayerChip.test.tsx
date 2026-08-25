import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LayerChip from "./LayerChip";

// 改善計画T331: dataStatus状態表示（statusDot/title）の肯定的な検証が無かったため追加。
// LayerChip.tsx: showStatusDot = on && dataStatus != null（OFF中は出さない・正常時
// （dataStatus未指定）も出さない）。mapLayers.ts: LAYER_DATA_STATUS_LABELSの3値
// （loading/empty/error）それぞれでtitle文言・状態別クラス（statusDot_${dataStatus}）が
// 正しく反映されることを確認する。
describe("LayerChip", () => {
  it("on=falseの場合はdataStatusを指定してもドット・titleを出さない（チップの見た目自体でON/OFFが分かるため）", () => {
    render(<LayerChip label="路面" on={false} dataStatus="error" onClick={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "路面" });
    expect(chip).not.toHaveAttribute("title");
    expect(chip.querySelector('[class*="statusDot"]')).not.toBeInTheDocument();
  });

  it("on=trueでdataStatus未指定（正常）の場合はドット・titleを出さない", () => {
    render(<LayerChip label="路面" on onClick={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "路面" });
    expect(chip).not.toHaveAttribute("title");
    expect(chip.querySelector('[class*="statusDot"]')).not.toBeInTheDocument();
  });

  it("on=trueかつdataStatus=loadingの場合、状態別クラスのドットと読み込み中の案内文をtitleに出す", () => {
    render(<LayerChip label="路面" on dataStatus="loading" onClick={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "路面" });
    expect(chip).toHaveAttribute("title", "読み込み中です");
    const dot = chip.querySelector('[class*="statusDot"]');
    expect(dot).toBeInTheDocument();
    expect(dot?.className).toMatch(/statusDot_loading/);
    expect(dot).toHaveAttribute("aria-hidden", "true");
  });

  it("on=trueかつdataStatus=emptyの場合、状態別クラスのドットとデータ無しの案内文をtitleに出す", () => {
    render(<LayerChip label="路面" on dataStatus="empty" onClick={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "路面" });
    expect(chip).toHaveAttribute("title", "この範囲に表示できるデータがありません");
    const dot = chip.querySelector('[class*="statusDot"]');
    expect(dot?.className).toMatch(/statusDot_empty/);
  });

  it("on=trueかつdataStatus=errorの場合、状態別クラスのドットと取得失敗の案内文をtitleに出す", () => {
    render(<LayerChip label="路面" on dataStatus="error" onClick={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "路面" });
    expect(chip).toHaveAttribute("title", "データの取得に失敗しました。しばらくしてから再読み込みしてください");
    const dot = chip.querySelector('[class*="statusDot"]');
    expect(dot?.className).toMatch(/statusDot_error/);
  });

  it("3状態のドットは互いに異なるクラスを持つ（見分けられる状態表現）", () => {
    const { rerender } = render(<LayerChip label="路面" on dataStatus="loading" onClick={vi.fn()} />);
    const loadingClass = screen.getByRole("button", { name: "路面" }).querySelector('[class*="statusDot_"]')?.className;

    rerender(<LayerChip label="路面" on dataStatus="empty" onClick={vi.fn()} />);
    const emptyClass = screen.getByRole("button", { name: "路面" }).querySelector('[class*="statusDot_"]')?.className;

    rerender(<LayerChip label="路面" on dataStatus="error" onClick={vi.fn()} />);
    const errorClass = screen.getByRole("button", { name: "路面" }).querySelector('[class*="statusDot_"]')?.className;

    expect(new Set([loadingClass, emptyClass, errorClass]).size).toBe(3);
  });
});
