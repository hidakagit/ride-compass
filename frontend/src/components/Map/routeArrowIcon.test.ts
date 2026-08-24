import { describe, expect, it } from "vitest";
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
