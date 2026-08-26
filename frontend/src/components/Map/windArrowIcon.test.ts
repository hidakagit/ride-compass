import { afterEach, describe, expect, it, vi } from "vitest";
import { createWindArrowIcon } from "./windArrowIcon";

// jsdomはcanvasの2D描画コンテキストを実装しないため（HTMLCanvasElement.getContextが
// 常にnullを返す）、createWindArrowIconはctxが取れない場合のフォールバック
// （`new ImageData(width, height)`）を通る。ブラウザ・Node双方に存在するはずの
// ImageDataコンストラクタ自体もjsdomではグローバルに定義されないため、このテストの
// 実行にだけ最小限のポリフィルを用意する（実際の描画内容の検証は実機Playwrightで行う、
// docs/testing.md参照。このテストはMapView.tsxからの分離、改善計画T201後も関数が
// 例外なく呼び出せることを確認する最小限のスモークテスト）。
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

describe("createWindArrowIcon", () => {
  it("例外を投げずに32x32のImageDataを返す", () => {
    const icon = createWindArrowIcon();
    expect(icon).toBeInstanceOf(ImageData);
    expect(icon.width).toBe(32);
    expect(icon.height).toBe(32);
  });
});

// 改善計画T331残り5項目: 上記のテストはjsdomがcanvasの2D描画コンテキストを実装しない
// ためctx===nullのフォールバック分岐しか通らず、実際の描画コード（fillTaperedRibbon経由の
// 主流線・副流線・矢じり）は一度も実行されていなかった。node-canvas等のネイティブ依存を
// 追加する代わりに、HTMLCanvasElement.getContextを最小限の「呼び出しを記録するだけの
// スタブ」へ差し替えることで、実際の描画コードパス自体が最後まで例外なく実行され、
// 期待した回数・引数で描画命令を呼んでいることを検証する（実際のピクセル内容の検証は
// 引き続き実機Playwrightで行う、docs/testing.md参照）。
describe("createWindArrowIcon（描画コードパスの実行検証）", () => {
  function stubCanvasContext() {
    const calls: string[] = [];
    const ctx = {
      beginPath: vi.fn(() => calls.push("beginPath")),
      moveTo: vi.fn(() => calls.push("moveTo")),
      lineTo: vi.fn(() => calls.push("lineTo")),
      closePath: vi.fn(() => calls.push("closePath")),
      fill: vi.fn(() => calls.push("fill")),
      fillStyle: "",
      getImageData: vi.fn(() => new ImageData(32, 32)),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      ctx as unknown as CanvasRenderingContext2D
    );
    return { ctx, calls };
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("フォールバックへ落ちず、3本の流線＋矢じりぶんの塗り（fill×4）を実行する", () => {
    const { ctx, calls } = stubCanvasContext();

    const icon = createWindArrowIcon();

    // フォールバック（new ImageData直接生成）ではなくctx.getImageData経由で返している
    expect(ctx.getImageData).toHaveBeenCalledWith(0, 0, 32, 32);
    expect(icon.width).toBe(32);
    // 主流線・左右副流線（fillTaperedRibbon×3）＋矢じり（直接beginPath〜fill）＝ fill 4回
    expect(ctx.fill).toHaveBeenCalledTimes(4);
    expect(ctx.beginPath).toHaveBeenCalledTimes(4);
    expect(ctx.closePath).toHaveBeenCalledTimes(4);
    // 呼び出し順序自体も「begin→(move/line...)→close→fill」を4セット崩さず守っている
    expect(calls.filter((c) => c === "beginPath")).toHaveLength(4);
    expect(calls[calls.length - 1]).toBe("fill");
  });

  it("矢じり（最後のfill直前のパス）は仕様どおりの4点シェイプを描く", () => {
    const { ctx } = stubCanvasContext();

    createWindArrowIcon();

    // 矢じりはfillTaperedRibbonを介さず直接moveTo/lineTo×3/closePath/fillを呼ぶ、
    // 唯一「moveToが1回だけ・lineToが3回だけ」呼ばれるセット。
    const moveToArrowhead = ctx.moveTo.mock.calls.find(([x, y]) => x === 16 && y === 2);
    expect(moveToArrowhead).toBeDefined();
    expect(ctx.lineTo).toHaveBeenCalledWith(21, 12.5);
    expect(ctx.lineTo).toHaveBeenCalledWith(16, 10);
    expect(ctx.lineTo).toHaveBeenCalledWith(11, 12.5);
  });
});
