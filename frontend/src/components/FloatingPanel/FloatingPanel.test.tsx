import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FloatingPanel from "./FloatingPanel";

describe("FloatingPanel", () => {
  it("open:falseのときは何も描画しない", () => {
    const { container } = render(
      <FloatingPanel open={false} onClose={() => {}} title="テストパネル">
        本文
      </FloatingPanel>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("open:trueのときタイトル・本文・headerButtonsを描画する", () => {
    render(
      <FloatingPanel open onClose={() => {}} title="テストパネル" headerButtons={<button>更新</button>}>
        本文テキスト
      </FloatingPanel>,
    );
    expect(screen.getByText("テストパネル")).toBeInTheDocument();
    expect(screen.getByText("本文テキスト")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新" })).toBeInTheDocument();
  });

  it("閉じるボタンでonCloseが呼ばれる", () => {
    const onClose = vi.fn();
    render(
      <FloatingPanel open onClose={onClose} title="テストパネル">
        本文
      </FloatingPanel>,
    );
    screen.getByRole("button", { name: "テストパネルを閉じる" }).click();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
