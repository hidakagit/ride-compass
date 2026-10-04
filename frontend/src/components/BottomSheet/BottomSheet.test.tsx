/**
 * `components/BottomSheet/BottomSheet.tsx`——スマホの下からせり上がるシートと、高さを範囲へ寄せる`clampSheetHeightVh`。
 *
 * 見るもの: 開いている間だけ見出しを名前に持つダイアログとして出すこと、閉じ方
 * （✕・Esc・下スワイプ）と閉じない操作（シートの外を押す・閉じないスワイプ）、高さを変える帯（いまの高さの表示・ドラッグ・矢印キー）で
 * 上がる高さ、開いたときに中身へ高さを合わせること（合わせ直す時機・合わせない指定・実寸が取れないとき）。
 *
 * ここで見ないもの: 高さを覚えて次に開いたときに使うこと → `app/page.tsx`（このシートは高さを受け取り、変えたい高さを
 * 上げるだけ）。シートの中身・見出しの脇の差し込み——受け取ったものをそのまま置くだけ。帯が出す変えられる範囲——
 * 寄せる範囲と同じ定数を出すだけ。範囲の両側へ寄せること——`clampSheetHeightVh`のテストが見る（シートの側は、
 * 寄せた値を上げることを片側で見る）。
 *
 * 中身の高さ・シートの高さはテスト環境に無いレイアウトの実寸なので、使うテストだけ`getBoundingClientRect`と
 * `clientHeight`をテストが決める。画面の高さはテスト環境の`window.innerHeight`をそのまま使う。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import BottomSheet, { clampSheetHeightVh } from "./BottomSheet";

type Props = React.ComponentProps<typeof BottomSheet>;

/** 高さの下限・上限。値を書き写さず、範囲の外の値を寄せた結果として取る（書き写すと、範囲を変えたときに
 * テストも一緒に動き、寄せることを誰も見なくなる）。 */
const FLOOR = clampSheetHeightVh(0);
const CEILING = clampSheetHeightVh(100);

function sheetElement(props: Partial<Props>, handlers: Pick<Props, "onClose" | "onHeightChange" | "onHeightCommit">) {
  return (
    <BottomSheet
      open
      title="ルート設定"
      titleId="sheet-title"
      headerAction={null}
      heightVh={50}
      autoFitHeight={false}
      {...handlers}
      {...props}
    >
      <p>中身</p>
    </BottomSheet>
  );
}

function renderSheet(props: Partial<Props> = {}) {
  const handlers = { onClose: vi.fn(), onHeightChange: vi.fn(), onHeightCommit: vi.fn() };
  const view = render(sheetElement(props, handlers));
  let current = props;
  return {
    ...handlers,
    /** 前に渡したpropsへ`next`を重ねて描き直す。 */
    rerender: (next: Partial<Props>) => {
      current = { ...current, ...next };
      view.rerender(sheetElement(current, handlers));
    },
    container: view.container,
  };
}

function handle() {
  return screen.getByRole("separator", { name: "パネルの高さを変更" });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("clampSheetHeightVh", () => {
  it("範囲の外の値はどれだけ外でも同じ下限・上限へ寄せ、範囲の中の値はそのまま通し、上限は画面いっぱい（地図を隠し切る高さ）より低い", () => {
    const inside = (FLOOR + CEILING) / 2 + 0.5;

    expect([-1000, inside, 1000].map(clampSheetHeightVh)).toEqual([FLOOR, inside, CEILING]);
    expect(FLOOR).toBeGreaterThan(0);
    expect(CEILING).toBeLessThan(100);
  });
});

describe("BottomSheet", () => {
  it("開いている間は、見出しを名前に持つダイアログを出す", () => {
    renderSheet();

    expect(screen.getByRole("dialog", { name: "ルート設定" })).toBeInTheDocument();
  });

  it("閉じている間は何も出さない", () => {
    const { container } = renderSheet({ open: false });

    expect(container).toBeEmptyDOMElement();
  });

  describe("閉じ方", () => {
    it("✕を押すと、閉じる操作が上がる", async () => {
      const { onClose } = renderSheet();

      await userEvent.click(screen.getByRole("button", { name: "閉じる" }));

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("シートの外の要素は押せ、押しても閉じる操作は上がらない", async () => {
      const onMapClick = vi.fn();
      const handlers = { onClose: vi.fn(), onHeightChange: vi.fn(), onHeightCommit: vi.fn() };
      render(
        <>
          <button type="button" onClick={onMapClick}>
            地図
          </button>
          {sheetElement({}, handlers)}
        </>,
      );

      await userEvent.click(screen.getByRole("button", { name: "地図" }));

      expect(onMapClick).toHaveBeenCalledTimes(1);
      expect(handlers.onClose).not.toHaveBeenCalled();
    });

    it("開いている間はEscで閉じる操作が上がり、ほかのキーでは上がらない", async () => {
      const { onClose } = renderSheet();

      await userEvent.keyboard("a");
      expect(onClose).not.toHaveBeenCalled();
      await userEvent.keyboard("{Escape}");

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("閉じたあとはEscで閉じる操作が上がらない", async () => {
      const { onClose, rerender } = renderSheet();
      rerender({ open: false });

      await userEvent.keyboard("{Escape}");

      expect(onClose).not.toHaveBeenCalled();
    });

    function swipe(from: Element, to: Element, start: { x: number; y: number }, end: { x: number; y: number }) {
      fireEvent.touchStart(from, { touches: [{ clientX: start.x, clientY: start.y }] });
      fireEvent.touchEnd(to, { changedTouches: [{ clientX: end.x, clientY: end.y }] });
    }

    it.each([
      ["61px下へ", { x: 100, y: 361 }, 1],
      ["60px下へ（ちょうど）", { x: 100, y: 360 }, 0],
      ["横の動きのほうが大きく下へ", { x: 300, y: 400 }, 0],
    ])("見出しを%sスワイプすると、閉じる操作が%s回上がる", (_, end, times) => {
      const { onClose } = renderSheet();
      const heading = screen.getByRole("heading", { name: "ルート設定" });

      swipe(heading, heading, { x: 100, y: 300 }, end);

      expect(onClose).toHaveBeenCalledTimes(times);
    });

    it.each([
      ["中身", () => screen.getByText("中身")],
      ["高さを変える帯", handle],
    ])("%sから始めた下スワイプでは閉じない", (_, from) => {
      const { onClose } = renderSheet();

      swipe(from(), from(), { x: 100, y: 300 }, { x: 100, y: 500 });

      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("高さを変える帯", () => {
    it("いまの高さを整数にして出す", () => {
      renderSheet({ heightVh: 42.6 });

      expect(handle()).toHaveAttribute("aria-valuenow", "43");
    });

    it("つまんで上へ動かすと動いたぶん高くした値を途中も上げ、離すと受け取っている高さを確定として上げる", () => {
      const { onHeightChange, onHeightCommit, rerender } = renderSheet({ heightVh: 50 });
      const moved = window.innerHeight / 4;

      fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 500 });
      fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 500 - moved });
      expect(onHeightChange).toHaveBeenLastCalledWith(75);
      expect(onHeightCommit).not.toHaveBeenCalled();
      rerender({ heightVh: 75 });
      fireEvent.pointerUp(handle(), { pointerId: 1, clientY: 500 - moved });

      expect(onHeightCommit.mock.calls).toEqual([[75]]);
    });

    it("上へ大きく動かしても、範囲の中に留める", () => {
      const { onHeightChange } = renderSheet({ heightVh: 50 });

      fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 400 });
      fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 400 - window.innerHeight });

      expect(onHeightChange).toHaveBeenLastCalledWith(CEILING);
    });

    it("つまんだ指と別の指の動きと離しは無視する", () => {
      const { onHeightChange, onHeightCommit } = renderSheet();

      fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 500 });
      fireEvent.pointerMove(handle(), { pointerId: 2, clientY: 300 });
      fireEvent.pointerUp(handle(), { pointerId: 2, clientY: 300 });

      expect(onHeightChange).not.toHaveBeenCalled();
      expect(onHeightCommit).not.toHaveBeenCalled();
    });

    it("つままずに動かしたり離したりしても何も上げず、離したあとの動きも無視する", () => {
      const { onHeightChange, onHeightCommit } = renderSheet();

      fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 300 });
      fireEvent.pointerUp(handle(), { pointerId: 1, clientY: 300 });
      fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 500 });
      fireEvent.pointerUp(handle(), { pointerId: 1, clientY: 500 });
      onHeightCommit.mockClear();
      fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 300 });

      expect(onHeightChange).not.toHaveBeenCalled();
      expect(onHeightCommit).not.toHaveBeenCalled();
    });

    /** 帯にフォーカスしてキーを押し、途中と確定で上がった高さを返す。 */
    async function pressOnHandle(key: string, from: number) {
      const { onHeightChange, onHeightCommit, container } = renderSheet({ heightVh: from });
      handle().focus();
      await userEvent.keyboard(key);
      const raised = { change: onHeightChange.mock.calls, commit: onHeightCommit.mock.calls };
      container.remove();
      return raised;
    }

    it("上の矢印と下の矢印は同じ幅だけ高さを上げ下げし、途中と確定の両方で同じ高さを上げる", async () => {
      const up = await pressOnHandle("{ArrowUp}", 50);
      const down = await pressOnHandle("{ArrowDown}", 50);

      expect(up.change).toEqual(up.commit);
      expect(down.change).toEqual(down.commit);
      expect(up.change[0][0]).toBeGreaterThan(50);
      expect(50 - down.change[0][0]).toBe(up.change[0][0] - 50);
    });

    it("上限の近くで上の矢印を押しても、範囲の中に留める", async () => {
      const { change, commit } = await pressOnHandle("{ArrowUp}", CEILING - 0.5);

      expect(change).toEqual([[CEILING]]);
      expect(commit).toEqual([[CEILING]]);
    });

    it("矢印の上下以外のキーでは何も上げない", async () => {
      const { onHeightChange, onHeightCommit } = renderSheet();
      handle().focus();

      await userEvent.keyboard("{ArrowLeft}");

      expect(onHeightChange).not.toHaveBeenCalled();
      expect(onHeightCommit).not.toHaveBeenCalled();
    });
  });

  describe("中身に合わせた高さ", () => {
    /** 高さの指定を外したときだけ中身の高さを、それ以外はシートの箱の高さを返す実寸。 */
    function stubLayout(naturalPx: number, boxPx = 300) {
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
        return new DOMRect(0, 0, 300, this.style.height === "auto" ? naturalPx : boxPx);
      });
      vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(boxPx);
    }

    it("開くと、高さの指定を外して測った中身の高さを画面の割合（切り上げ）にして上げ、指定は元へ戻す", () => {
      stubLayout(window.innerHeight * 0.333);

      const { onHeightChange } = renderSheet({ autoFitHeight: true, heightVh: 50 });

      expect(onHeightChange.mock.calls).toEqual([[34]]);
      expect(screen.getByRole("dialog").style.height).toBe("50vh");
    });

    it("中身が高いときも、範囲の中に留める", () => {
      stubLayout(window.innerHeight * ((CEILING + 100) / 200));

      const { onHeightChange } = renderSheet({ autoFitHeight: true });

      expect(onHeightChange.mock.calls).toEqual([[CEILING]]);
    });

    it("開いている間は合わせ直さず、中身が別物になった（fitKeyが変わった）ときと開き直したときに合わせ直す", () => {
      stubLayout(window.innerHeight * 0.3);
      const { onHeightChange, rerender } = renderSheet({ autoFitHeight: true, fitKey: "設定" });
      onHeightChange.mockClear();

      rerender({ heightVh: 61 });
      expect(onHeightChange).not.toHaveBeenCalled();

      stubLayout(window.innerHeight * 0.75);
      rerender({ fitKey: "結果" });
      expect(onHeightChange.mock.calls).toEqual([[75]]);

      stubLayout(window.innerHeight * 0.25);
      rerender({ open: false });
      rerender({ open: true });
      expect(onHeightChange.mock.calls).toEqual([[75], [25]]);
    });

    it("合わせない指定のときは、開いても高さを上げない", () => {
      stubLayout(window.innerHeight * 0.3);

      const { onHeightChange } = renderSheet({ autoFitHeight: false });

      expect(onHeightChange).not.toHaveBeenCalled();
    });

    it("実寸が取れないとき（テスト環境のまま）は、高さを上げない", () => {
      const { onHeightChange } = renderSheet({ autoFitHeight: true });

      expect(onHeightChange).not.toHaveBeenCalled();
    });
  });
});
