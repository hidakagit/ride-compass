import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import WindBearingSlider from "./WindBearingSlider";

// @fseehawer/react-circular-sliderの内部実装（ポインタ操作による角度計算）はテスト対象外
// のため、onChangeを外から呼べる薄いボタンへ差し替える。
vi.mock("@fseehawer/react-circular-slider", () => ({
  default: ({ onChange, children }: { onChange: (next: number | string) => void; children: React.ReactNode }) => (
    <div>
      <button type="button" onClick={() => onChange(123)}>
        emit-number
      </button>
      <button type="button" onClick={() => onChange("not-a-number")}>
        emit-invalid-string
      </button>
      {children}
    </div>
  ),
}));

// 改善計画T471: ライブラリのonChangeがnumber以外を渡した場合、Number(next)がNaNになりうる
// 経路にガードが無かった（NaNをそのまま親のstateへ伝えるとcardinalLabel(NaN)等の表示・
// 以後のbearing_degを使う評価が壊れる）回帰テスト。
describe("WindBearingSlider", () => {
  it("数値のonChangeはそのまま伝播する", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WindBearingSlider value={0} onChange={onChange} ariaLabel="向き" />);

    await user.click(screen.getByText("emit-number"));

    expect(onChange).toHaveBeenCalledWith(123);
  });

  it("数値へ変換できない値のonChangeは伝播しない（NaNを親へ渡さない）", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WindBearingSlider value={0} onChange={onChange} ariaLabel="向き" />);

    await user.click(screen.getByText("emit-invalid-string"));

    expect(onChange).not.toHaveBeenCalled();
  });
});
