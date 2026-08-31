import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import WindBearingSlider from "./WindBearingSlider";

// ユーザー指摘（2026-08-31、「コンパスは…触りにくい&進行方向を直感的に示していない」）を
// 受け、@fseehawer/react-circular-sliderを使わない自前実装（中心から伸びる矢印を直接
// つかんで回すダイヤル）へ作り替えた。ポインタドラッグの角度計算は
// getBoundingClientRect()に依存しhappy-domでは実寸(0)しか返らず単体テストで再現できない
// （RouteSettingsPanel.test.tsxの帯グラフ境界ドラッグと同じ制約、docs/tasks/T495.md
// 参照）ため、happy-domでも決定的に検証できるキーボード操作（矢印キー）経路を検証する。
// 実際のポインタドラッグはBrowserペインでの実機確認で検証済み（docs/tasks/T501.md参照）。
describe("WindBearingSlider", () => {
  it("ArrowRightキーで5度ずつ時計回りに進む", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WindBearingSlider value={10} onChange={onChange} ariaLabel="向き" />);

    const dial = screen.getByRole("slider", { name: "向き" });
    dial.focus();
    await user.keyboard("{ArrowRight}");

    expect(onChange).toHaveBeenCalledWith(15);
  });

  it("ArrowLeftキーで5度ずつ反時計回りに進む", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WindBearingSlider value={10} onChange={onChange} ariaLabel="向き" />);

    const dial = screen.getByRole("slider", { name: "向き" });
    dial.focus();
    await user.keyboard("{ArrowLeft}");

    expect(onChange).toHaveBeenCalledWith(5);
  });

  it("0度を下回ると360度側へラップする", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WindBearingSlider value={2} onChange={onChange} ariaLabel="向き" />);

    const dial = screen.getByRole("slider", { name: "向き" });
    dial.focus();
    await user.keyboard("{ArrowLeft}");

    expect(onChange).toHaveBeenCalledWith(357);
  });

  it("360度を超えると0度側へラップする", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WindBearingSlider value={358} onChange={onChange} ariaLabel="向き" />);

    const dial = screen.getByRole("slider", { name: "向き" });
    dial.focus();
    await user.keyboard("{ArrowRight}");

    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("現在値・8方位ラベルをaria-valuenow/aria-valuetextへ反映する", () => {
    render(<WindBearingSlider value={95} onChange={vi.fn()} ariaLabel="向き" />);

    const dial = screen.getByRole("slider", { name: "向き" });
    expect(dial).toHaveAttribute("aria-valuenow", "95");
    expect(dial).toHaveAttribute("aria-valuetext", "95度（東）");
  });
});
