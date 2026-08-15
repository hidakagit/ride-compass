import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BottomSheet from "./BottomSheet";

function renderSheet(onClose: () => void) {
  return render(
    <div>
      <nav aria-label="パネル切り替え">
        <button type="button">ルートを作る</button>
      </nav>
      <button type="button">地図(シート外)</button>
      <BottomSheet
        open
        onClose={onClose}
        title="テストシート"
        titleId="test-sheet-title"
        heightVh={50}
        onHeightChange={() => {}}
        onHeightCommit={() => {}}
      >
        <p>シートの中身がここに長く続く想定のテキスト</p>
      </BottomSheet>
    </div>,
  );
}

// 実機フィードバック対応: シート内容のスクロールで誤って閉じる不具合の修正と、
// シート外タップ/下部タブバー除外の新しい閉じる挙動を検証する。
describe("BottomSheet", () => {
  it("シート外をpointerdownすると閉じる", () => {
    const onClose = vi.fn();
    renderSheet(onClose);

    fireEvent.pointerDown(screen.getByRole("button", { name: "地図(シート外)" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("シート内をpointerdownしても閉じない", () => {
    const onClose = vi.fn();
    renderSheet(onClose);

    fireEvent.pointerDown(screen.getByText("シートの中身がここに長く続く想定のテキスト"));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("下部タブバー（パネル切り替え）をpointerdownしても閉じない（専用トグルに任せる）", () => {
    const onClose = vi.fn();
    renderSheet(onClose);

    fireEvent.pointerDown(screen.getByRole("button", { name: "ルートを作る" }));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("✕ボタンのクリックで閉じる", async () => {
    const onClose = vi.fn();
    renderSheet(onClose);

    fireEvent.click(screen.getByRole("button", { name: "閉じる" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("パネル内容の大きな縦タッチ移動（スクロール相当）では閉じない", () => {
    const onClose = vi.fn();
    renderSheet(onClose);
    const content = screen.getByText("シートの中身がここに長く続く想定のテキスト");

    fireEvent.touchStart(content, { touches: [{ clientX: 100, clientY: 100 }] });
    fireEvent.touchEnd(content, { changedTouches: [{ clientX: 100, clientY: 300 }] });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("シート自体（本文の外）での下スワイプでは引き続き閉じる", () => {
    const onClose = vi.fn();
    renderSheet(onClose);
    const sheet = screen.getByRole("dialog");

    fireEvent.touchStart(sheet, { touches: [{ clientX: 100, clientY: 100 }] });
    fireEvent.touchEnd(sheet, { changedTouches: [{ clientX: 100, clientY: 300 }] });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
