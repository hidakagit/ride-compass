import { describe, expect, it } from "vitest";
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
