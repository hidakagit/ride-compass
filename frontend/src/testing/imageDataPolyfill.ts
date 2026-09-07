/**
 * DOM環境に`ImageData`が無い場合の最小ポリフィル。
 *
 * happy-dom/jsdomはcanvasの2D描画コンテキストを実装せず（`getContext`が常にnullを返す）、
 * `ImageData`コンストラクタもグローバルに定義しない。canvasが使えないときのフォールバックで
 * `new ImageData(w, h)`を返す実装（routeArrowIcon・windArrowIcon）のテストが、
 * 呼び出せること自体を確認するために使う。描画内容そのものの検証は実機で行う
 * （docs/testing.md参照）。
 */
export function installImageDataPolyfill() {
  if (typeof globalThis.ImageData !== "undefined") return;

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
