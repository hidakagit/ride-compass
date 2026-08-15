import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RoadFilterEditor from "./RoadFilterEditor";

function baseProps() {
  return {
    savedHiddenKeys: { surface: [], highway: [] } as Record<"surface" | "highway", readonly string[]>,
    onApply: vi.fn(),
  };
}

// 旧RoadFilterDialog（地図上の⚙から開くモーダル）の「下書き編集→適用で確定」の挙動を
// サイドバー内エディタとして引き継いだもの。適用まで親の実状態に影響しないことが要点。
describe("RoadFilterEditor", () => {
  it("2軸（路面の種類・道路の種類）分のチェックボックスが並ぶ", () => {
    render(<RoadFilterEditor {...baseProps()} />);
    expect(screen.getByText("路面の種類で絞り込み")).toBeInTheDocument();
    expect(screen.getByText("道路の種類で絞り込み")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /自転車・歩行者道/ })).toBeInTheDocument();
  });

  it("変更が無い間は適用・破棄ボタンとも押せない", () => {
    render(<RoadFilterEditor {...baseProps()} />);
    expect(screen.getByRole("button", { name: "適用" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "編集を破棄" })).toBeDisabled();
  });

  it("チェックボックスを操作しただけではonApplyは呼ばれない（下書きのまま）", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<RoadFilterEditor {...baseProps()} onApply={onApply} />);

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));

    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByText("未適用の変更があります")).toBeInTheDocument();
  });

  it("適用を押すと2軸分の下書きがまとめてonApplyへ渡る（組み合わせ絞り込み）", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<RoadFilterEditor {...baseProps()} onApply={onApply} />);

    await user.click(screen.getByRole("checkbox", { name: /砂利・締固め/ }));
    await user.click(screen.getByRole("checkbox", { name: /幹線道路/ }));
    await user.click(screen.getByRole("button", { name: "適用" }));

    expect(onApply).toHaveBeenCalledWith({
      surface: ["gravel"],
      highway: ["arterial"],
    });
  });

  it("編集を破棄すると下書きが適用済みの状態に戻り、onApplyは呼ばれない", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<RoadFilterEditor {...baseProps()} onApply={onApply} />);

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "編集を破棄" }));

    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.queryByText("未適用の変更があります")).not.toBeInTheDocument();
  });

  it("適用済みの状態を初期値として下書きを作る（前回適用分が反映されている）", () => {
    render(<RoadFilterEditor {...baseProps()} savedHiddenKeys={{ surface: ["gravel"], highway: [] }} />);

    expect(screen.getByRole("checkbox", { name: /砂利・締固め/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
    // 適用中の絞り込みがあることは閉じた状態のラベルからも分かる
    expect(screen.getByText(/絞り込みを編集（適用中）/)).toBeInTheDocument();
  });
});
