/**
 * `components/FloatingPanel/FloatingPanel.tsx`——開発者向けパネルの、画面に浮かぶ殻。
 *
 * 見るもの: 開いている間だけ見出し・見出しの操作・閉じるボタン・中身を出すこと、閉じる操作が上がること、
 * 開いたときに横は画面の中央・縦は指定の高さへ置くこと、本文の高さの上限を指定どおりにすること。
 *
 * ここで見ないもの: つまみでのドラッグと、画面の外へ出ないこと——react-rndの振る舞い。幅（`widthRem`と画面幅の小さいほう）
 * ——幅の式は`min()`の中にCSS変数を持ち、テスト環境（happy-dom）はその宣言を捨てて残さない。
 *
 * 描いた幅はテスト環境に無いレイアウトの実寸なので、`getBoundingClientRect`の幅をテストが決める。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import FloatingPanel from "./FloatingPanel";

function panel(props: Partial<React.ComponentProps<typeof FloatingPanel>> = {}) {
  return (
    <FloatingPanel
      open
      onClose={vi.fn()}
      title="デバッグログ"
      headerButtons={null}
      topRem={4}
      widthRem={22}
      maxHeightPx={420}
      {...props}
    >
      <p>本文</p>
    </FloatingPanel>
  );
}

function renderPanel(props: Partial<React.ComponentProps<typeof FloatingPanel>> = {}) {
  const onClose = vi.fn();
  const view = render(panel({ onClose, ...props }));
  return { onClose, view };
}

/** パネルを置いている位置（react-rndが付ける`translate`）。 */
function panelPosition(): { x: number; y: number } {
  const positioned = screen
    .getByRole("separator", { name: "ドラッグしてパネルを移動" })
    .closest<HTMLElement>('[style*="translate"]');
  const match = positioned?.style.transform.match(/translate\((-?[\d.]+)px, *(-?[\d.]+)px\)/);
  if (!match) throw new Error("パネルの位置が見つからない");
  return { x: Number(match[1]), y: Number(match[2]) };
}

function stubPanelWidth(width: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, width, 100));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("FloatingPanel", () => {
  it("開いている間は、見出し・見出しの操作・閉じるボタン・中身を出す", () => {
    renderPanel({ headerButtons: <button type="button">クリア</button> });

    expect(screen.getByText("デバッグログ")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "クリア" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "デバッグログを閉じる" })).toBeInTheDocument();
    expect(screen.getByText("本文")).toBeInTheDocument();
  });

  it("閉じている間は何も出さない", () => {
    const { view } = renderPanel({ open: false });

    expect(view.container).toBeEmptyDOMElement();
  });

  it("閉じるボタンを押すと、閉じる操作が上がる", async () => {
    const { onClose } = renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "デバッグログを閉じる" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("開くと、横は画面の中央・縦は指定の高さ（rem）へ置く", () => {
    stubPanelWidth(200);

    renderPanel({ topRem: 2 });

    const rootFontSizePx = parseFloat(getComputedStyle(document.documentElement).fontSize);
    expect(panelPosition()).toEqual({ x: (window.innerWidth - 200) / 2, y: 2 * rootFontSizePx });
  });

  it("画面より広いときは、左端へ寄せる", () => {
    stubPanelWidth(window.innerWidth + 100);

    renderPanel();

    expect(panelPosition().x).toBe(0);
  });

  it("閉じて開き直すと、中央へ置き直す", () => {
    stubPanelWidth(200);
    const { view, onClose } = renderPanel();
    const centered = panelPosition();

    view.rerender(panel({ open: false, onClose }));
    stubPanelWidth(400);
    view.rerender(panel({ onClose }));

    expect(panelPosition()).toEqual({ x: (window.innerWidth - 400) / 2, y: centered.y });
  });

  it("本文の高さの上限を、指定どおりにする", () => {
    renderPanel({ maxHeightPx: 300 });

    const panel = screen.getByText("本文").closest<HTMLElement>('[style*="max-height"]');
    expect(panel?.style.maxHeight).toBe("300px");
  });
});
