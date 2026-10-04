/**
 * `components/ui/NumberInput/NumberInput.tsx`——打っている途中の文字を部品が持つ数値欄。
 *
 * 見るもの: 欄に出す文字、値を渡す時機（`commitOn`の2通り）と渡す値、数として読めない文字を渡さないこと、
 * 欄を離れたあとの表示、打ったまま欄ごと消えたとき。
 *
 * ここで見ないもの: 範囲への丸め——呼び出し側が値で行う（この部品は受け取った値を出すだけ）。呼び出し側の
 * `onFocus`・`onBlur`・`onKeyDown`とそれ以外の属性・参照——中の入力欄へそのまま渡すだけ。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NumberInput } from "./NumberInput";

type CommitOn = React.ComponentProps<typeof NumberInput>["commitOn"];

function renderInput(props: Partial<React.ComponentProps<typeof NumberInput>> = {}) {
  const onValueChange = vi.fn();
  const view = render(
    <NumberInput value={25} onValueChange={onValueChange} commitOn="commit" aria-label="速度" {...props} />,
  );
  const input = screen.getByRole("spinbutton", { name: "速度" }) as HTMLInputElement;
  return { input, onValueChange, view };
}

describe("NumberInput", () => {
  it("欄に入ると中身が全部選ばれ、打った文字で置き換わる", async () => {
    const { input } = renderInput();

    await userEvent.click(input);
    await userEvent.keyboard("3");

    expect(input.value).toBe("3");
  });

  it("打つたびに渡す（commitOn=input）欄は、数として読めた時点で毎回渡す", async () => {
    const { input, onValueChange } = renderInput({ commitOn: "input" });

    await userEvent.click(input);
    await userEvent.keyboard("31");

    expect(onValueChange.mock.calls).toEqual([[3], [31]]);
  });

  it.each<[string, CommitOn, string]>([
    ["打つたびに渡す欄を空にして離れる", "input", "{Backspace}{Tab}"],
    ["離れたときに渡す欄を空にして離れる", "commit", "{Backspace}{Tab}"],
    ["離れたときに渡す欄へ打たずに離れる", "commit", "{Tab}"],
  ])("%sと、何も渡さない", async (_, commitOn, keys) => {
    const { input, onValueChange } = renderInput({ commitOn });

    await userEvent.click(input);
    await userEvent.keyboard(keys);

    expect(onValueChange).not.toHaveBeenCalled();
  });

  it.each([
    ["欄を離れる", "31{Tab}"],
    ["Enterを押す", "31{Enter}"],
  ])("離れたときに渡す（commitOn=commit）欄で%sと、読めた値を1回渡し、表示は値へ戻る", async (_, keys) => {
    const { input, onValueChange } = renderInput();

    await userEvent.click(input);
    await userEvent.keyboard(keys);

    expect(onValueChange.mock.calls).toEqual([[31]]);
    expect(input).toHaveValue(25);
  });

  it("離れたときに渡す欄へ打ったまま欄ごと消えると、その時点の受け取り口へ打った値を渡す", async () => {
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

  it.each<[string, CommitOn, string]>([
    ["打つたびに渡す欄へ打ったまま", "input", "4"],
    ["離れたときに渡す欄で、離れて渡したあと", "commit", "31{Tab}"],
    ["離れたときに渡す欄を空にしたまま", "commit", "{Backspace}"],
  ])("%s欄ごと消えると、改めては渡さない", async (_, commitOn, keys) => {
    const { input, onValueChange, view } = renderInput({ commitOn });
    await userEvent.click(input);
    await userEvent.keyboard(keys);
    onValueChange.mockClear();

    view.unmount();

    expect(onValueChange).not.toHaveBeenCalled();
  });
});
