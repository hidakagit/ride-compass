import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BottomSheet, { clampSheetHeightVh, MAX_SHEET_HEIGHT_VH, MIN_SHEET_HEIGHT_VH } from "./BottomSheet";

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
// 「シート外タップ・スクロール（地図操作）では閉じない」という挙動を検証する
// （一度シート外タップでも閉じる仕様を試したが、地図を操作しながら凡例を見たいという
// フィードバックで撤回した経緯があるため、リグレッションを防ぐテストとして残す）。
describe("BottomSheet", () => {
  it("シート外をpointerdownしても閉じない（地図操作を妨げない）", () => {
    const onClose = vi.fn();
    renderSheet(onClose);

    fireEvent.pointerDown(screen.getByRole("button", { name: "地図(シート外)" }));

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

// 改善計画T331: 高さ調整系（ドラッグ・キーボード操作・clampSheetHeightVh）の肯定的な
// 検証が無かったため追加。
describe("BottomSheet 高さ調整（改善計画T331）", () => {
  describe("clampSheetHeightVh", () => {
    it("範囲内の値はそのまま返す", () => {
      expect(clampSheetHeightVh(50)).toBe(50);
    });

    it("MIN_SHEET_HEIGHT_VHを下回る値はMIN_SHEET_HEIGHT_VHへ切り上げる", () => {
      expect(clampSheetHeightVh(0)).toBe(MIN_SHEET_HEIGHT_VH);
      expect(clampSheetHeightVh(-10)).toBe(MIN_SHEET_HEIGHT_VH);
    });

    it("MAX_SHEET_HEIGHT_VHを上回る値はMAX_SHEET_HEIGHT_VHへ切り下げる", () => {
      expect(clampSheetHeightVh(100)).toBe(MAX_SHEET_HEIGHT_VH);
    });

    it("境界値そのものはそのまま返す", () => {
      expect(clampSheetHeightVh(MIN_SHEET_HEIGHT_VH)).toBe(MIN_SHEET_HEIGHT_VH);
      expect(clampSheetHeightVh(MAX_SHEET_HEIGHT_VH)).toBe(MAX_SHEET_HEIGHT_VH);
    });
  });

  function renderHandle(heightVh: number, onHeightChange: (vh: number) => void, onHeightCommit: (vh: number) => void) {
    render(
      <BottomSheet
        open
        onClose={() => {}}
        title="テストシート"
        titleId="test-sheet-title-2"
        heightVh={heightVh}
        onHeightChange={onHeightChange}
        onHeightCommit={onHeightCommit}
      >
        <p>本文</p>
      </BottomSheet>,
    );
    return screen.getByRole("separator", { name: "パネルの高さを変更" });
  }

  describe("キーボード操作（ハンドルの矢印キー）", () => {
    it("ArrowUpで高さがHEIGHT_KEY_STEP_VH(5vh)分増え、onHeightChange/onHeightCommit双方が呼ばれる", () => {
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(50, onHeightChange, onHeightCommit);

      fireEvent.keyDown(handle, { key: "ArrowUp" });

      expect(onHeightChange).toHaveBeenCalledWith(55);
      expect(onHeightCommit).toHaveBeenCalledWith(55);
    });

    it("ArrowDownで高さがHEIGHT_KEY_STEP_VH(5vh)分減る", () => {
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(50, onHeightChange, onHeightCommit);

      fireEvent.keyDown(handle, { key: "ArrowDown" });

      expect(onHeightChange).toHaveBeenCalledWith(45);
      expect(onHeightCommit).toHaveBeenCalledWith(45);
    });

    it("MAX_SHEET_HEIGHT_VH付近でArrowUpを押しても上限を超えない", () => {
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(MAX_SHEET_HEIGHT_VH - 2, onHeightChange, onHeightCommit);

      fireEvent.keyDown(handle, { key: "ArrowUp" });

      expect(onHeightChange).toHaveBeenCalledWith(MAX_SHEET_HEIGHT_VH);
      expect(onHeightCommit).toHaveBeenCalledWith(MAX_SHEET_HEIGHT_VH);
    });

    it("MIN_SHEET_HEIGHT_VH付近でArrowDownを押しても下限を下回らない", () => {
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(MIN_SHEET_HEIGHT_VH + 2, onHeightChange, onHeightCommit);

      fireEvent.keyDown(handle, { key: "ArrowDown" });

      expect(onHeightChange).toHaveBeenCalledWith(MIN_SHEET_HEIGHT_VH);
      expect(onHeightCommit).toHaveBeenCalledWith(MIN_SHEET_HEIGHT_VH);
    });

    it("ArrowUp/ArrowDown以外のキーでは高さを変更しない", () => {
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(50, onHeightChange, onHeightCommit);

      fireEvent.keyDown(handle, { key: "Enter" });

      expect(onHeightChange).not.toHaveBeenCalled();
      expect(onHeightCommit).not.toHaveBeenCalled();
    });
  });

  describe("ハンドルのポインタードラッグ", () => {
    // jsdom/happy-domはsetPointerCapture/releasePointerCaptureを実装しないため
    // no-opでスタブする（AxisStudio.test.tsxのResizeObserverMockと同じ、既知の欠落への対処）。
    if (!Element.prototype.setPointerCapture) {
      Element.prototype.setPointerCapture = vi.fn();
    }
    if (!Element.prototype.releasePointerCapture) {
      Element.prototype.releasePointerCapture = vi.fn();
    }

    it("ハンドルを上方向へドラッグすると高さが増え、onHeightChangeが随時・onHeightCommitはpointerup時のみ呼ばれる", () => {
      vi.spyOn(window, "innerHeight", "get").mockReturnValue(1000);
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(50, onHeightChange, onHeightCommit);

      fireEvent.pointerDown(handle, { pointerId: 1, clientY: 500 });
      expect(onHeightCommit).not.toHaveBeenCalled();

      // 上方向(clientYが減る)ドラッグ100pxはinnerHeight(1000px)の10% → +10vh
      fireEvent.pointerMove(handle, { pointerId: 1, clientY: 400 });
      expect(onHeightChange).toHaveBeenCalledWith(60);
      expect(onHeightCommit).not.toHaveBeenCalled();

      fireEvent.pointerUp(handle, { pointerId: 1, clientY: 400 });
      // pointerup時点ではheightVh prop自体はまだ50のまま(呼び出し側が再renderして更新する前)
      // のため、onHeightCommitはheightVh(=50)で呼ばれる（BottomSheet.tsx: handleHandlePointerUp参照）。
      expect(onHeightCommit).toHaveBeenCalledWith(50);

      vi.restoreAllMocks();
    });

    it("ドラッグ中はMAX_SHEET_HEIGHT_VHを超えない", () => {
      vi.spyOn(window, "innerHeight", "get").mockReturnValue(1000);
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(MAX_SHEET_HEIGHT_VH - 2, onHeightChange, onHeightCommit);

      fireEvent.pointerDown(handle, { pointerId: 1, clientY: 500 });
      // 上方向へ大きく動かす(+50vh相当)が上限でクランプされる
      fireEvent.pointerMove(handle, { pointerId: 1, clientY: 0 });

      expect(onHeightChange).toHaveBeenCalledWith(MAX_SHEET_HEIGHT_VH);

      vi.restoreAllMocks();
    });

    it("別のpointerIdのpointermove/pointerupは無視する（複数指の誤反応防止）", () => {
      vi.spyOn(window, "innerHeight", "get").mockReturnValue(1000);
      const onHeightChange = vi.fn();
      const onHeightCommit = vi.fn();
      const handle = renderHandle(50, onHeightChange, onHeightCommit);

      fireEvent.pointerDown(handle, { pointerId: 1, clientY: 500 });
      fireEvent.pointerMove(handle, { pointerId: 2, clientY: 400 });
      expect(onHeightChange).not.toHaveBeenCalled();

      fireEvent.pointerUp(handle, { pointerId: 2, clientY: 400 });
      expect(onHeightCommit).not.toHaveBeenCalled();

      vi.restoreAllMocks();
    });
  });
});

// 開いた時点で中身に合う高さへ合わせる（シートが中身より高いと、そのぶん地図が隠れたまま
// 空白を見せることになる）。実寸はレイアウトを持たない環境では取れないため、
// clientHeight/scrollHeightを差し替えて検証する。
describe("BottomSheet（開いたときに中身の高さへ合わせる）", () => {
  // 高さ指定を外したときの実測（naturalHeightOf）を再現する。レイアウトを持たない環境では
  // getBoundingClientRectが常に0を返すため、高さ指定が"auto"の間だけ中身なりの高さを返す。
  function withStubbedMetrics(naturalHeightPx: number, run: () => void) {
    const client = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
    const rect = HTMLElement.prototype.getBoundingClientRect;
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 406 });
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
      const height = this.style.height === "auto" ? naturalHeightPx : 406;
      return { height, width: 390, top: 0, left: 0, right: 390, bottom: height, x: 0, y: 0, toJSON: () => ({}) };
    };
    try {
      run();
    } finally {
      if (client) Object.defineProperty(HTMLElement.prototype, "clientHeight", client);
      HTMLElement.prototype.getBoundingClientRect = rect;
    }
  }

  function renderWithHeight(onHeightChange: (vh: number) => void) {
    render(
      <BottomSheet
        open
        onClose={() => {}}
        title="テストシート"
        titleId="test-sheet-title"
        heightVh={50}
        onHeightChange={onHeightChange}
        onHeightCommit={() => {}}
      >
        <p>中身</p>
      </BottomSheet>,
    );
  }

  it("中身がシートより低ければ、その高さまで縮める", () => {
    const onHeightChange = vi.fn();
    window.innerHeight = 812;
    // 中身なりの高さ302px → 812pxの37.2% → 38vh（切り上げ）
    withStubbedMetrics(302, () => renderWithHeight(onHeightChange));

    expect(onHeightChange).toHaveBeenCalledWith(38);
  });

  it("中身が上限を超えても上限までしか広げない（地図を完全には隠さない）", () => {
    const onHeightChange = vi.fn();
    window.innerHeight = 812;
    withStubbedMetrics(5000, () => renderWithHeight(onHeightChange));

    expect(onHeightChange).toHaveBeenCalledWith(MAX_SHEET_HEIGHT_VH);
  });

  it("中身が下限より低くても、下限までしか縮めない", () => {
    const onHeightChange = vi.fn();
    window.innerHeight = 812;
    withStubbedMetrics(60, () => renderWithHeight(onHeightChange));

    expect(onHeightChange).toHaveBeenCalledWith(MIN_SHEET_HEIGHT_VH);
  });

  it("実寸が取れない実行では高さを触らない", () => {
    const onHeightChange = vi.fn();
    window.innerHeight = 812;
    renderWithHeight(onHeightChange);

    expect(onHeightChange).not.toHaveBeenCalled();
  });
});
