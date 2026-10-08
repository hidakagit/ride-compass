/**
 * `components/UsageGuide/UsageGuide.tsx`——説明を見る状態（押した部品は動かず、その部品の名前と使い方を出す）。
 * 押された要素から部品と名前・使い方を引く`usageTarget.ts`は、この部品の中の手順として通す。
 *
 * 見るもの: 案内の「やめる」、部品を押したときに部品が動かず説明が出ること、説明に出す名前（読み上げ名の引き方）と
 * 使い方の文（自分か囲む要素の印・無いときの文言）、ラベルを押したときに説明する入力、押せないボタンでも出ること、
 * 動かした（なぞった・取り消された）押し方では出さないこと、部品の外を押したとき（押し操作が外へ届かないことも）、キー操作（Esc・Enter・Space・
 * 値を動かすキー）、説明の✕・部品の外・説明の外へのフォーカスのどれでも説明だけを閉じて部品を選ぶ続きへ戻り、終えるのは「やめる」とEscだけなこと、
 * 案内と説明の面の上の操作は止めないこと、説明している部品を囲む枠と測り直し、
 * マウスの操作は既定の動きまで止め、タッチは既定の動き（スクロール）を残すこと、終えたら部品が動くこと、
 * 閉じた展開する部品・選ばれていないタブの説明の「中を見る」（出す部品と出さない部品）、それで開いた浮きパネルの中の部品も説明し、説明の✕と
 * 終える操作では閉じないこと。
 *
 * ここで見ないもの:
 * - 案内の文言——部品の宣言で、書き写して突き合わせるだけになる
 * - 共有部品が使い方の文を印に書くこと → それぞれの部品（`components/ui/Button/Button.tsx`等）。ここでは本物の
 *   `Button`で1つだけ通す
 * - 説明の面の置き方 → Radixの位置取り（`side`・`collisionPadding`）に任せている
 * - 案内をつまみで動かすこと → `components/FloatingPanel/FloatingPanel.tsx`（react-rndの振る舞い）
 *
 * 部品の実寸はテスト環境に無いレイアウトの値なので、枠を見るテストだけ`getBoundingClientRect`をテストが決める。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Disclosure from "@/components/Disclosure/Disclosure";
import { Button } from "@/components/ui/Button/Button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
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

    it("説明を出している間なら、説明だけを閉じて続け、押し操作は外の要素へ届かない", async () => {
      const onMapClick = vi.fn();
      const onEnd = vi.fn();
      render(
        <>
          <Button usage="いまの条件で候補を作ります。">生成</Button>
          <div onClick={onMapClick}>地図</div>
          <UsageGuide onEnd={onEnd} />
        </>,
      );
      await userEvent.click(screen.getByRole("button", { name: "生成" }));

      await userEvent.click(screen.getByText("地図"));

      expect(explanation()).toBeNull();
      expect(onMapClick).not.toHaveBeenCalled();
      expect(onEnd).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole("button", { name: "生成" }));
      expect(explanation()).toHaveTextContent("いまの条件で候補を作ります。");
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

  it("説明の✕を押すと、説明と枠だけを閉じ、続けて別の部品の説明を出せる", async () => {
    const { onEnd, onGenerate } = renderScreen();
    const frame = () => document.querySelector<HTMLElement>('[aria-hidden="true"][style]');
    await userEvent.click(screen.getByRole("button", { name: "地図の色分け" }));
    expect(frame()).not.toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "説明を閉じる" }));

    expect(onEnd).not.toHaveBeenCalled();
    expect(explanation()).toBeNull();
    expect(frame()).toBeNull();
    expect(screen.getByRole("button", { name: "やめる" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
    expect(explanation()).toHaveTextContent("いまの条件で候補を作ります。");
  });

  it("説明を出している間にフォーカスを説明の外へ移すと、説明だけを閉じる", async () => {
    const { onEnd } = renderScreen();
    await userEvent.click(screen.getByRole("button", { name: "地図の色分け" }));

    act(() => screen.getByRole("slider", { name: "重み" }).focus());

    expect(explanation()).toBeNull();
    expect(onEnd).not.toHaveBeenCalled();
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

  describe("「中を見る」で開いた浮きパネル", () => {
    function renderPopoverScreen() {
      const onEnd = vi.fn();
      const onSpeed = vi.fn();
      function Screen() {
        const [active, setActive] = useState(true);
        return (
          <>
            <p>本文の文字</p>
            <Button usage="いまの条件で候補を作ります。">生成</Button>
            <Popover>
              <PopoverTrigger asChild>
                <Button usage="速さを決める面を開きます。">想定速度</Button>
              </PopoverTrigger>
              <PopoverContent aria-label="想定速度の面">
                <Button onClick={onSpeed} usage="速さを1つ上げます。">
                  速く
                </Button>
              </PopoverContent>
            </Popover>
            {active && (
              <UsageGuide
                onEnd={() => {
                  onEnd();
                  setActive(false);
                }}
              />
            )}
          </>
        );
      }
      render(<Screen />);
      return { onEnd, onSpeed };
    }
    const popover = () => screen.queryByRole("dialog", { name: "想定速度の面" });

    async function openInside() {
      await userEvent.click(screen.getByRole("button", { name: "想定速度" }));
      expect(popover()).toBeNull();
      await userEvent.click(screen.getByRole("button", { name: "中を見る" }));
    }

    it("開くボタンの説明の「中を見る」で開き、中の部品は動かずに説明が出て、✕でも開いたまま", async () => {
      const { onEnd, onSpeed } = renderPopoverScreen();

      await openInside();
      expect(popover()).toBeInTheDocument();
      expect(explanation()).toBeNull();

      await userEvent.click(screen.getByRole("button", { name: "速く" }));
      expect(onSpeed).not.toHaveBeenCalled();
      expect(explanation()).toHaveTextContent("速さを1つ上げます。");
      expect(explanation()).not.toHaveTextContent("中を見る");

      await userEvent.click(screen.getByRole("button", { name: "説明を閉じる" }));
      expect(popover()).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "速く" }));
      expect(explanation()).toHaveTextContent("速さを1つ上げます。");
      expect(popover()).toBeInTheDocument();
      expect(onEnd).not.toHaveBeenCalled();
    });

    it.each([
      ["「やめる」で", async () => userEvent.click(screen.getByRole("button", { name: "やめる" }))],
      ["Escで", async () => userEvent.keyboard("{Escape}")],
    ])("%s終えても、浮きパネルは開いたまま残る", async (_, operate) => {
      const { onEnd } = renderPopoverScreen();
      await openInside();
      await userEvent.click(screen.getByRole("button", { name: "速く" }));

      await operate();

      expect(onEnd).toHaveBeenCalledTimes(1);
      expect(popover()).toBeInTheDocument();
    });
  });

  describe("「中を見る」を出す部品", () => {
    it("閉じた折りたたみの見出しは「中を見る」で開き、中の部品も説明する", async () => {
      render(
        <>
          <Disclosure summary="条件" usage="条件の欄を開きます。">
            <Button usage="距離を決めます。">距離</Button>
          </Disclosure>
          <UsageGuide onEnd={vi.fn()} />
        </>,
      );
      await userEvent.click(screen.getByRole("button", { name: "条件" }));
      expect(screen.queryByRole("button", { name: "距離" })).toBeNull();

      await userEvent.click(screen.getByRole("button", { name: "中を見る" }));
      await userEvent.click(screen.getByRole("button", { name: "距離" }));

      expect(explanation()).toHaveTextContent("距離を決めます。");
    });

    it("選ばれていないタブは「中を見る」で切り替わり、中の部品も説明する", async () => {
      render(
        <>
          <Tabs defaultValue="generate">
            <TabsList>
              <TabsTrigger value="generate">条件</TabsTrigger>
              <TabsTrigger value="weights" usage="重みを決めます。">
                重み
              </TabsTrigger>
            </TabsList>
            <TabsContent value="generate" />
            <TabsContent value="weights">
              <Button usage="評価軸の重さを変えます。">勾配</Button>
            </TabsContent>
          </Tabs>
          <UsageGuide onEnd={vi.fn()} />
        </>,
      );
      await userEvent.click(screen.getByRole("tab", { name: "重み" }));
      expect(screen.queryByRole("button", { name: "勾配" })).toBeNull();

      await userEvent.click(screen.getByRole("button", { name: "中を見る" }));
      await userEvent.click(screen.getByRole("button", { name: "勾配" }));

      expect(explanation()).toHaveTextContent("評価軸の重さを変えます。");
    });

    it.each([
      ["開いている部品", { "aria-expanded": true }],
      ["選ばれているタブ", { role: "tab", "aria-selected": true }],
      ["別の面を開く部品（確かめのダイアログ等）", { "aria-expanded": false, "aria-haspopup": "dialog" as const }],
    ])("%sには出さない", async (_, attributes) => {
      render(
        <>
          <button type="button" {...attributes}>
            対象
          </button>
          <UsageGuide onEnd={vi.fn()} />
        </>,
      );

      await userEvent.click(screen.getByText("対象"));

      expect(explanation()).toHaveTextContent("対象");
      expect(screen.queryByRole("button", { name: "中を見る" })).toBeNull();
    });
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
