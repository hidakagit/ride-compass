import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/Button/Button";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup/ToggleGroup";
import UsageGuide from "./UsageGuide";

// 説明を見る状態: どの部品を押しても部品は動かず、押した部品の名前と使い方が出る。

function renderGuide() {
  const onEnd = vi.fn();
  const onGenerate = vi.fn();
  const onModeChange = vi.fn();
  const onChecked = vi.fn();
  render(
    <div>
      <p>本文の文字</p>
      <Button onClick={onGenerate} aria-label="ルート生成" usage="いまの条件で候補を作ります。">
        生成
      </Button>
      <Button disabled aria-label="絞り込みをすべて解除する">
        ×
      </Button>
      <label>
        <Checkbox checked={false} onCheckedChange={onChecked} aria-label="周囲も塗る" />
        周囲も塗る
      </label>
      <ToggleGroup value="loop" onValueChange={onModeChange} aria-label="モード" usage="作るルートの形を選びます。">
        <ToggleGroupItem value="loop">周回</ToggleGroupItem>
        <ToggleGroupItem value="destination">目的地</ToggleGroupItem>
      </ToggleGroup>
      <UsageGuide onEnd={onEnd} />
    </div>,
  );
  return { onEnd, onGenerate, onModeChange, onChecked };
}

/** 指やマウスで押して離す（押せないボタンにはclickが届かないため、押す・離すで送る）。 */
function tap(element: Element, move = 0) {
  fireEvent.pointerDown(element, { clientX: 0, clientY: 0 });
  fireEvent.mouseDown(element);
  fireEvent.pointerUp(element, { clientX: move, clientY: 0 });
  fireEvent.mouseUp(element);
  fireEvent.click(element);
}

const explanation = () => screen.getByRole("dialog", { name: "使い方の説明" });

describe("UsageGuide（説明を見る状態）", () => {
  it("押した部品は動かず、その名前と使い方が出る", () => {
    const { onGenerate } = renderGuide();
    tap(screen.getByRole("button", { name: "ルート生成" }));
    expect(onGenerate).not.toHaveBeenCalled();
    expect(within(explanation()).getByText("ルート生成")).toBeInTheDocument();
    expect(within(explanation()).getByText("いまの条件で候補を作ります。")).toBeInTheDocument();
  });

  it("押せないボタンでも名前が出る。文を持たない部品は、説明が無いことを出す", () => {
    renderGuide();
    tap(screen.getByRole("button", { name: "絞り込みをすべて解除する" }));
    expect(within(explanation()).getByText("絞り込みをすべて解除する")).toBeInTheDocument();
    expect(within(explanation()).getByText("この部品の説明はまだありません。")).toBeInTheDocument();
  });

  it("ラベルの文字を押すと、中の入力を説明し、入力は切り替わらない", () => {
    const { onChecked } = renderGuide();
    tap(screen.getByText("周囲も塗る"));
    expect(onChecked).not.toHaveBeenCalled();
    expect(within(explanation()).getByText("周囲も塗る")).toBeInTheDocument();
  });

  it("文を持たない選択肢は、囲む部品の文を出し、選択は変わらない", () => {
    const { onModeChange } = renderGuide();
    tap(screen.getByRole("radio", { name: "目的地" }));
    expect(onModeChange).not.toHaveBeenCalled();
    expect(within(explanation()).getByText("目的地")).toBeInTheDocument();
    expect(within(explanation()).getByText("作るルートの形を選びます。")).toBeInTheDocument();
  });

  it("押したまま動かした（なぞった）ときは、説明を出さない", () => {
    renderGuide();
    tap(screen.getByRole("button", { name: "ルート生成" }), 40);
    expect(screen.queryByRole("dialog", { name: "使い方の説明" })).not.toBeInTheDocument();
  });

  it("部品の外を押しても、説明を出す前なら状態を続ける。出したあとなら終える", () => {
    const { onEnd } = renderGuide();
    tap(screen.getByText("本文の文字"));
    expect(onEnd).not.toHaveBeenCalled();
    tap(screen.getByRole("button", { name: "ルート生成" }));
    tap(screen.getByText("本文の文字"));
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("「やめる」・説明の✕・Escで終える", () => {
    const { onEnd } = renderGuide();
    fireEvent.click(screen.getByRole("button", { name: "やめる" }));
    expect(onEnd).toHaveBeenCalledTimes(1);
    tap(screen.getByRole("button", { name: "ルート生成" }));
    fireEvent.click(within(explanation()).getByRole("button", { name: "説明を閉じる" }));
    expect(onEnd).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onEnd).toHaveBeenCalledTimes(3);
  });

  it("キーボードでは、フォーカスのある部品をEnterで説明する", () => {
    const { onGenerate } = renderGuide();
    const button = screen.getByRole("button", { name: "ルート生成" });
    button.focus();
    fireEvent.keyDown(button, { key: "Enter" });
    expect(onGenerate).not.toHaveBeenCalled();
    expect(within(explanation()).getByText("いまの条件で候補を作ります。")).toBeInTheDocument();
  });
});
