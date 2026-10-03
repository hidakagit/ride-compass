/**
 * `components/ui/NumberInput/NumberInput.tsx`——打っている途中の文字を部品が持つ数値欄。
 *
 * 見るもの: 欄に出す文字、値を渡す時機（`commitOn`の2通り）と渡す値、数として読めない文字を渡さないこと、
 * 欄を離れたあとの表示、打ったまま欄ごと消えたとき、呼び出し側の`onFocus`・`onBlur`・`onKeyDown`と
 * それ以外の属性・参照が届くこと。
 *
 * ここで見ないもの: 範囲への丸め——呼び出し側が値で行う（この部品は受け取った値を出すだけ）。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { NumberInput } from "./NumberInput";

function renderInput(props: Partial<React.ComponentProps<typeof NumberInput>> = {}) {
  const onValueChange = vi.fn();
  const view = render(
    <NumberInput value={25} onValueChange={onValueChange} commitOn="commit" aria-label="速度" {...props} />,
  );
  const input = screen.getByRole("spinbutton", { name: "速度" }) as HTMLInputElement;
  return { input, onValueChange, view };
}

describe("NumberInput", () => {
  it("値を文字にして出す", () => {
    const { input } = renderInput({ value: 12.5 });

    expect(input).toHaveValue(12.5);
  });

  it("欄に入ると中身が全部選ばれ、打った文字で置き換わる", async () => {
    const { input } = renderInput();

    await userEvent.click(input);
    await userEvent.keyboard("3");

    expect(input.value).toBe("3");
  });

  describe("打つたびに渡す（commitOn=input）", () => {
    it("数として読めた時点で毎回渡す", async () => {
      const { input, onValueChange } = renderInput({ commitOn: "input" });

      await userEvent.click(input);
      await userEvent.keyboard("31");

      expect(onValueChange.mock.calls).toEqual([[3], [31]]);
    });

    it("空にしたときは渡さず、欄を離れても渡さない", async () => {
      const { input, onValueChange } = renderInput({ commitOn: "input" });

      await userEvent.clear(input);
      await userEvent.tab();

      expect(onValueChange).not.toHaveBeenCalled();
    });

    it("打ったまま欄ごと消えても、改めては渡さない", async () => {
      const { input, onValueChange, view } = renderInput({ commitOn: "input" });
      await userEvent.click(input);
      await userEvent.keyboard("4");
      onValueChange.mockClear();

      view.unmount();

      expect(onValueChange).not.toHaveBeenCalled();
    });
  });

  describe("欄を離れたとき・Enterで渡す（commitOn=commit）", () => {
    it("打っている間は渡さず、打った文字を出し続ける", async () => {
      const { input, onValueChange } = renderInput();

      await userEvent.click(input);
      await userEvent.keyboard("3");
      fireEvent.change(input, { target: { value: "3." } });

      expect(onValueChange).not.toHaveBeenCalled();
      expect(input.value).toBe("3.");
    });

    it("欄を離れると、読めた値を1回渡し、表示は受け取っている値へ戻る", async () => {
      const { input, onValueChange } = renderInput();

      await userEvent.click(input);
      await userEvent.keyboard("31");
      await userEvent.tab();

      expect(onValueChange.mock.calls).toEqual([[31]]);
      expect(input).toHaveValue(25);
    });

    it("Enterを押すと、読めた値を1回渡す", async () => {
      const { input, onValueChange } = renderInput();

      await userEvent.click(input);
      await userEvent.keyboard("18{Enter}");

      expect(onValueChange.mock.calls).toEqual([[18]]);
    });

    it("空のまま離れると渡さず、表示は受け取っている値へ戻る", async () => {
      const { input, onValueChange } = renderInput();

      await userEvent.clear(input);
      await userEvent.tab();

      expect(onValueChange).not.toHaveBeenCalled();
      expect(input).toHaveValue(25);
    });

    it("打たずに離れると渡さない", async () => {
      const { input, onValueChange } = renderInput();

      await userEvent.click(input);
      await userEvent.tab();

      expect(onValueChange).not.toHaveBeenCalled();
    });

    it("打ったまま欄ごと消えると、その時点の受け取り口へ打った値を渡す", async () => {
      const first = vi.fn();
      const latest = vi.fn();
      const { input, view } = renderInput({ onValueChange: first });
      await userEvent.click(input);
      await userEvent.keyboard("7");
      view.rerender(<NumberInput value={25} onValueChange={latest} commitOn="commit" aria-label="速度" />);

      view.unmount();

      expect(first).not.toHaveBeenCalled();
      expect(latest.mock.calls).toEqual([[7]]);
    });

    it("離れて渡したあとに欄ごと消えても、もう一度は渡さない", async () => {
      const { input, onValueChange, view } = renderInput();
      await userEvent.click(input);
      await userEvent.keyboard("31");
      await userEvent.tab();

      view.unmount();

      expect(onValueChange.mock.calls).toEqual([[31]]);
    });

    it("空のまま欄ごと消えると渡さない", async () => {
      const { input, onValueChange, view } = renderInput();
      await userEvent.clear(input);

      view.unmount();

      expect(onValueChange).not.toHaveBeenCalled();
    });
  });

  it("呼び出し側の`onFocus`・`onBlur`・`onKeyDown`も呼ばれる", async () => {
    const onFocus = vi.fn();
    const onBlur = vi.fn();
    const onKeyDown = vi.fn();
    const { input } = renderInput({ onFocus, onBlur, onKeyDown });

    await userEvent.click(input);
    await userEvent.keyboard("{Enter}");
    await userEvent.tab();

    expect(onFocus).toHaveBeenCalledTimes(1);
    expect(onKeyDown.mock.calls.map(([event]) => event.key)).toEqual(["Enter", "Tab"]);
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  it("それ以外の属性と参照は中の入力欄へ届く", () => {
    const ref = createRef<HTMLInputElement>();
    const { input } = renderInput({ ref, min: 5, max: 40, step: 0.5, disabled: true });

    expect(ref.current).toBe(input);
    expect(input).toHaveAttribute("min", "5");
    expect(input).toHaveAttribute("max", "40");
    expect(input).toHaveAttribute("step", "0.5");
    expect(input).toBeDisabled();
  });
});
