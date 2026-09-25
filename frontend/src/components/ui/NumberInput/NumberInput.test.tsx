import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NumberInput } from "./NumberInput";

function setup(commitOn: "input" | "commit", value = 10) {
  const onValueChange = vi.fn();
  const view = render(<NumberInput aria-label="値" value={value} onValueChange={onValueChange} commitOn={commitOn} />);
  return { onValueChange, input: screen.getByRole("spinbutton", { name: "値" }) as HTMLInputElement, ...view };
}

describe("NumberInput（打つたびに渡す）", () => {
  it("数として読めた時点で毎回渡し、読めない途中の文字（空）は渡さない", () => {
    const { onValueChange, input } = setup("input");

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.change(input, { target: { value: "12" } });

    expect(onValueChange.mock.calls).toEqual([[12]]);
  });

  it("欄を離れても、もう一度は渡さない", () => {
    const { onValueChange, input } = setup("input");

    fireEvent.change(input, { target: { value: "12" } });
    fireEvent.blur(input);

    expect(onValueChange).toHaveBeenCalledTimes(1);
  });
});

describe("NumberInput（確定したときだけ渡す）", () => {
  it("打っている間は渡さず、打った文字をそのまま出す", () => {
    const { onValueChange, input } = setup("commit");

    fireEvent.change(input, { target: { value: "12" } });

    expect(onValueChange).not.toHaveBeenCalled();
    expect(input.value).toBe("12");
  });

  it("欄を離れたとき・Enterで、読めた値を1回だけ渡す", () => {
    const blurred = setup("commit");
    fireEvent.change(blurred.input, { target: { value: "12" } });
    fireEvent.blur(blurred.input);
    expect(blurred.onValueChange.mock.calls).toEqual([[12]]);
    blurred.unmount();

    const entered = setup("commit");
    fireEvent.change(entered.input, { target: { value: "7" } });
    fireEvent.keyDown(entered.input, { key: "Enter" });
    expect(entered.onValueChange.mock.calls).toEqual([[7]]);
  });

  it("読めない文字のまま離れたら何も渡さず、表示は今の値へ戻る", () => {
    const { onValueChange, input } = setup("commit", 10);

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);

    expect(onValueChange).not.toHaveBeenCalled();
    expect(input.value).toBe("10");
  });

  it("打ったまま欄ごと消えても、打った値を渡す（消える要素には離れた知らせが届かない）", () => {
    const { onValueChange, input, unmount } = setup("commit");

    fireEvent.change(input, { target: { value: "15" } });
    unmount();

    expect(onValueChange.mock.calls).toEqual([[15]]);
  });

  it("確定した後に消えても、もう一度は渡さない", () => {
    const { onValueChange, input, unmount } = setup("commit");

    fireEvent.change(input, { target: { value: "15" } });
    fireEvent.blur(input);
    unmount();

    expect(onValueChange).toHaveBeenCalledTimes(1);
  });
});
