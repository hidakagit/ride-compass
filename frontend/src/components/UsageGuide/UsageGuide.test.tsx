/**
 * `components/UsageGuide/UsageGuide.tsx`——説明を見る状態（押した部品は動かず、その部品の名前と使い方を出す）。
 * 押された要素から部品と名前・使い方を引く`usageTarget.ts`は、この部品の中の手順として通す。
 *
 * 見るもの: 案内の「やめる」、部品を押したときに部品が動かず説明が出ること、説明に出す名前（読み上げ名の引き方）と
 * 使い方の文（自分か囲む要素の印・無いときの文言）、ラベルを押したときに説明する入力、押せないボタンでも出ること、
 * 動かした（なぞった・取り消された）押し方では出さないこと、部品の外を押したとき、キー操作（Esc・Enter・Space・
 * 値を動かすキー）、案内と説明の面の上の操作は止めないこと、説明している部品を囲む枠と測り直し、
 * 説明の外へフォーカスを移したときに終えること、マウスの操作は既定の動きまで止め、タッチは既定の動き（スクロール）を残すこと、
 * 終えたら部品が動くこと。
 *
 * ここで見ないもの:
 * - 案内の文言——部品の宣言で、書き写して突き合わせるだけになる
 * - 共有部品が使い方の文を印に書くこと → それぞれの部品（`components/ui/Button/Button.tsx`等）。ここでは本物の
 *   `Button`で1つだけ通す
 * - 説明の面の置き方（部品の上端の中央・画面の端との間）——Radix Popoverの振る舞いで、テスト環境に実寸が無い
 *
 * 部品の実寸はテスト環境に無いレイアウトの値なので、枠を見るテストだけ`getBoundingClientRect`をテストが決める。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/Button/Button";
import UsageGuide from "./UsageGuide";

function renderScreen() {
  const onEnd = vi.fn();
  const onGenerate = vi.fn();
  const onPartKeyDown = vi.fn();
  const view = render(
    <div>
      <p>本文の文字</p>
      <Button onClick={onGenerate} usage="いまの条件で候補を作ります。">
        生成
      </Button>
      <button type="button" aria-label="地図の色分け" data-usage="色で道の評価を見分けます。">
        色
      </button>
      <span id="label-distance">距離</span>
      <span id="label-unit">km</span>
      <button type="button" aria-labelledby="label-distance label-unit">
        −
      </button>
      <div data-usage="チェックを外した段階を地図から隠します。">
        <label htmlFor="level-1">段階1</label>
        <input id="level-1" type="checkbox" />
      </div>
      <button type="button">
        {"  地図の\n  明るさ  "}
        <span>▼</span>
      </button>
      <button type="button" title="現在地へ移動">
        <svg aria-hidden="true" />
      </button>
      <button type="button" data-testid="no-name">
        <svg aria-hidden="true" />
      </button>
      <button type="button" disabled>
        保存
      </button>
      <div role="slider" aria-label="重み" aria-valuenow={3} tabIndex={0} onKeyDown={onPartKeyDown} />
      <div data-usage="地図の凡例です。">凡例</div>
      <UsageGuide onEnd={onEnd} />
    </div>,
  );
  return { onEnd, onGenerate, onPartKeyDown, view };
}

function explanation() {
  return screen.queryByRole("dialog", { name: "使い方の説明" });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UsageGuide", () => {
  it("案内の「やめる」を押すと、終える操作が上がる", async () => {
    const { onEnd } = renderScreen();

    await userEvent.click(screen.getByRole("button", { name: "やめる" }));

    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("部品を押すと、部品は動かず、名前と使い方を出す", async () => {
    const { onGenerate, onEnd } = renderScreen();

    await userEvent.click(screen.getByRole("button", { name: "生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
    expect(onEnd).not.toHaveBeenCalled();
    expect(explanation()).toHaveTextContent("生成");
    expect(explanation()).toHaveTextContent("いまの条件で候補を作ります。");
  });

  it.each([
    ["読み上げの名前の指定", "地図の色分け"],
    ["名前を指す要素（複数なら空白でつなぐ）", "距離 km"],
    ["中の文字（空白はまとめる）", "地図の 明るさ ▼"],
    ["中の文字が無ければ題", "現在地へ移動"],
  ])("名前は%sから引く", async (_, name) => {
    renderScreen();

    await userEvent.click(screen.getByRole("button", { name }));

    expect(explanation()?.querySelector("p")).toHaveTextContent(name);
  });

  it("名前を引けない部品は「この部品」とし、使い方の文が無ければまだ無いと出す", async () => {
    renderScreen();

    await userEvent.click(screen.getByTestId("no-name"));

    expect(explanation()).toHaveTextContent("この部品");
    expect(explanation()).toHaveTextContent("この部品の説明はまだありません。");
  });

  it("部品の中の要素を押しても、その部品を説明する", async () => {
    renderScreen();

    await userEvent.click(screen.getByText("▼"));

    expect(explanation()?.querySelector("p")).toHaveTextContent("地図の 明るさ ▼");
  });

  it.each([
    ["入力", () => screen.getByRole("checkbox", { name: "段階1" })],
    ["ラベル", () => screen.getByText("段階1")],
  ])("%sを押すと、ラベルの文字を名前に、囲む要素の使い方を出し、入力は動かない", async (_, pressed) => {
    renderScreen();

    await userEvent.click(pressed());

    expect(explanation()?.querySelector("p")).toHaveTextContent("段階1");
    expect(explanation()).toHaveTextContent("チェックを外した段階を地図から隠します。");
    expect(screen.getByRole("checkbox", { name: "段階1" })).not.toBeChecked();
  });

  it("使い方の印を持つ素の要素も、部品として説明する", async () => {
    renderScreen();

    await userEvent.click(screen.getByText("凡例"));

    expect(explanation()).toHaveTextContent("地図の凡例です。");
  });

  it("押せないボタンでも、離したときに説明を出す", () => {
    renderScreen();
    const disabled = screen.getByRole("button", { name: "保存" });

    fireEvent.pointerDown(disabled, { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(disabled, { clientX: 0, clientY: 0 });

    expect(explanation()).toHaveTextContent("保存");
  });

  it.each([
    ["10px（ちょうど）動かして離す", 10, true],
    ["10pxより大きく動かして離す", 11, false],
  ])("%sと、説明を出すか（%s）が決まる", (_, distance, shown) => {
    renderScreen();
    const button = screen.getByRole("button", { name: "地図の色分け" });

    fireEvent.pointerDown(button, { clientX: 100, clientY: 100 });
    fireEvent.pointerUp(button, { clientX: 100 + distance * 0.6, clientY: 100 + distance * 0.8 });

    expect(explanation() !== null).toBe(shown);
  });

  it("押したあと取り消されたら、離しても説明を出さない", () => {
    renderScreen();
    const button = screen.getByRole("button", { name: "地図の色分け" });

    fireEvent.pointerDown(button, { clientX: 0, clientY: 0 });
    fireEvent.pointerCancel(button);
    fireEvent.pointerUp(button, { clientX: 0, clientY: 0 });

    expect(explanation()).not.toBeInTheDocument();
  });

  describe("部品の外を押したとき", () => {
    it("説明を出す前なら、何もしない", async () => {
      const { onEnd } = renderScreen();

      await userEvent.click(screen.getByText("本文の文字"));

      expect(onEnd).not.toHaveBeenCalled();
      expect(explanation()).not.toBeInTheDocument();
    });

    it("説明を出している間なら、終える操作が上がる", async () => {
      const { onEnd } = renderScreen();
      await userEvent.click(screen.getByRole("button", { name: "地図の色分け" }));

      await userEvent.click(screen.getByText("本文の文字"));

      expect(onEnd).toHaveBeenCalledTimes(1);
    });
  });

  describe("キー操作", () => {
    it("Escを押すと、説明を出す前でも終える操作が上がる", async () => {
      const { onEnd } = renderScreen();

      await userEvent.keyboard("{Escape}");

      expect(onEnd).toHaveBeenCalledTimes(1);
    });

    it("描き直して終える操作が変わっても、新しいほうへ上げる", async () => {
      const onEnd = vi.fn();
      const latest = vi.fn();
      // 同じ木の形で描き直す（形が変わると部品が作り直され、新しい操作で始まるので、入れ替えを見なくなる）。
      const view = render(<UsageGuide onEnd={onEnd} />);
      view.rerender(<UsageGuide onEnd={latest} />);

      await userEvent.keyboard("{Escape}");

      expect(onEnd).not.toHaveBeenCalled();
      expect(latest).toHaveBeenCalledTimes(1);
    });

    it.each(["{Enter}", " "])("フォーカスのある部品で「%s」を押すと、部品は動かず説明を出す", async (key) => {
      const { onGenerate } = renderScreen();
      screen.getByRole("button", { name: "生成" }).focus();

      await userEvent.keyboard(key);

      expect(onGenerate).not.toHaveBeenCalled();
      expect(explanation()).toHaveTextContent("いまの条件で候補を作ります。");
    });

    it("値を動かすキーは部品へ届かず、ほかのキーは届く", async () => {
      const { onPartKeyDown } = renderScreen();
      screen.getByRole("slider", { name: "重み" }).focus();

      await userEvent.keyboard("{ArrowUp}");
      expect(onPartKeyDown).not.toHaveBeenCalled();
      await userEvent.keyboard("a");

      expect(onPartKeyDown).toHaveBeenCalledTimes(1);
    });

    it("案内の上のボタンはキーでも押せる", async () => {
      const { onEnd } = renderScreen();
      screen.getByRole("button", { name: "やめる" }).focus();

      await userEvent.keyboard("{Enter}");

      expect(onEnd).toHaveBeenCalledTimes(1);
    });
  });

  it("説明の✕を押すと、終える操作が上がる", async () => {
    const { onEnd } = renderScreen();
    await userEvent.click(screen.getByRole("button", { name: "地図の色分け" }));

    await userEvent.click(screen.getByRole("button", { name: "説明を閉じる" }));

    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("説明を出している間にフォーカスを説明の外へ移すと、終える操作が上がる", async () => {
    const { onEnd } = renderScreen();
    await userEvent.click(screen.getByRole("button", { name: "地図の色分け" }));

    act(() => screen.getByRole("slider", { name: "重み" }).focus());

    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("説明している部品を枠で囲み、スクロールと画面の大きさが変わると測り直す", async () => {
    renderScreen();
    const button = screen.getByRole("button", { name: "地図の色分け" });
    const rect = vi.spyOn(button, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 20, 30, 40));
    const frame = () => document.querySelector<HTMLElement>('[aria-hidden="true"][style]');
    expect(frame()).toBeNull();

    await userEvent.click(button);
    expect(frame()?.style).toMatchObject({ left: "10px", top: "20px", width: "30px", height: "40px" });

    rect.mockReturnValue(new DOMRect(10, 5, 30, 40));
    fireEvent.scroll(window);
    expect(frame()?.style.top).toBe("5px");

    rect.mockReturnValue(new DOMRect(50, 5, 30, 40));
    fireEvent(window, new Event("resize"));
    expect(frame()?.style.left).toBe("50px");
  });

  it("部品の上のマウスの操作は既定の動きまで止め、タッチは部品へ届けずにスクロールを残す", () => {
    renderScreen();
    const target = screen.getByRole("button", { name: "地図の色分け" });

    expect(fireEvent.mouseDown(target)).toBe(false);
    expect(fireEvent.contextMenu(target)).toBe(false);
    expect(fireEvent.dblClick(target)).toBe(false);
    expect(fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }] })).toBe(true);
  });

  it("タッチは部品の受け口へ届かない", () => {
    const onTouchStart = vi.fn();
    render(
      <>
        <button type="button" onTouchStart={onTouchStart}>
          押す
        </button>
        <UsageGuide onEnd={vi.fn()} />
      </>,
    );

    fireEvent.touchStart(screen.getByRole("button", { name: "押す" }), { touches: [{ clientX: 0, clientY: 0 }] });

    expect(onTouchStart).not.toHaveBeenCalled();
  });

  it("説明を見る状態を外すと、部品は押したとおりに動く", async () => {
    const { onGenerate, view } = renderScreen();

    view.rerender(
      <Button onClick={onGenerate} usage="いまの条件で候補を作ります。">
        生成
      </Button>,
    );
    await userEvent.click(screen.getByRole("button", { name: "生成" }));

    expect(onGenerate).toHaveBeenCalledTimes(1);
  });
});
