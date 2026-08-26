import { afterEach, describe, expect, it, vi } from "vitest";
import { createRouteArrowIcon } from "./routeArrowIcon";

// jsdomはcanvasの2D描画コンテキストを実装しないため（HTMLCanvasElement.getContextが
// 常にnullを返す）、createRouteArrowIconはctxが取れない場合のフォールバック
// （`new ImageData(width, height)`）を通る。windArrowIcon.test.tsと同じ理由・同じ最小限の
// ポリフィルで、実際の描画内容の検証は実機で行う（docs/testing.md参照）。このテストは
// 例外なく呼び出せることを確認する最小限のスモークテスト。
if (typeof globalThis.ImageData === "undefined") {
  class ImageDataPolyfill {
    data: Uint8ClampedArray;
    width: number;
    height: number;
    constructor(width: number, height: number) {
      this.width = width;
      this.height = height;
      this.data = new Uint8ClampedArray(width * height * 4);
    }
  }
  // @ts-expect-error テスト環境専用の最小ポリフィル、DOM libの完全な型とは一致しない
  globalThis.ImageData = ImageDataPolyfill;
}

describe("createRouteArrowIcon", () => {
  it("例外を投げずに20x20のImageDataを返す", () => {
    const icon = createRouteArrowIcon();
    expect(icon).toBeInstanceOf(ImageData);
    expect(icon.width).toBe(20);
    expect(icon.height).toBe(20);
  });
});

// 改善計画T331残り5項目: 上記のテストはjsdomのctx===nullフォールバック分岐しか通らず、
// 実際のシェブロン描画コードは一度も実行されていなかった（windArrowIcon.test.tsと同型の
// カバレッジ欠落）。HTMLCanvasElement.getContextを呼び出しを記録するだけのスタブへ
// 差し替え、実際の描画コードパスが最後まで例外なく実行され、期待した描画命令を呼んで
// いることを検証する（ピクセル内容自体の検証は引き続き実機Playwrightで行う）。
describe("createRouteArrowIcon（描画コードパスの実行検証）", () => {
  function stubCanvasContext() {
    const ctx = {
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      closePath: vi.fn(),
      fill: vi.fn(),
      fillStyle: "",
      getImageData: vi.fn(() => new ImageData(20, 20)),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      ctx as unknown as CanvasRenderingContext2D
    );
    return ctx;
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("フォールバックへ落ちず、右（東）を向くシェブロン1つぶんの塗りを実行する", () => {
    const ctx = stubCanvasContext();

    const icon = createRouteArrowIcon();

    // フォールバック（new ImageData直接生成）ではなくctx.getImageData経由で返している
    expect(ctx.getImageData).toHaveBeenCalledWith(0, 0, 20, 20);
    expect(icon.width).toBe(20);
    expect(ctx.beginPath).toHaveBeenCalledTimes(1);
    expect(ctx.closePath).toHaveBeenCalledTimes(1);
    expect(ctx.fill).toHaveBeenCalledTimes(1);
    // シェブロンは中心(10,10)を基準に、先端(17,10)→尾上(3,4)→中間(6.5,10)→尾下(3,16)
    expect(ctx.moveTo).toHaveBeenCalledWith(17, 10);
    expect(ctx.lineTo).toHaveBeenCalledWith(3, 4);
    expect(ctx.lineTo).toHaveBeenCalledWith(6.5, 10);
    expect(ctx.lineTo).toHaveBeenCalledWith(3, 16);
  });
});
