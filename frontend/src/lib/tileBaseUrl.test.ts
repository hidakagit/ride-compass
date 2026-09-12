// @vitest-environment node
import { describe, expect, it } from "vitest";
import { resolveTileBaseUrl } from "./tileBaseUrl";

// 配信オリジンの決め方の唯一の検証場所。`process.env`も`window`も触らずに済むよう、
// 判断は`resolveTileBaseUrl`（引数だけで決まる純関数）へ出してある——`process.env`は
// テストファイルをまたいで共有されるため、環境変数を立てて検証すると並行実行中の別ファイルの
// 期待値を静かに書き換える（docs/testing.md「環境変数に依存する挙動のテスト」参照）。
describe("resolveTileBaseUrl", () => {
  it("配信オリジンが設定されていればそのオリジンを使う", () => {
    expect(resolveTileBaseUrl("https://tiles.example.test", "http://localhost:3000")).toBe(
      "https://tiles.example.test",
    );
  });

  it("末尾スラッシュは重複しないよう除去する", () => {
    expect(resolveTileBaseUrl("https://tiles.example.test//", null)).toBe("https://tiles.example.test");
  });

  it("空文字は未設定と同じ扱いにする（フロント自身のオリジンを使う）", () => {
    expect(resolveTileBaseUrl("", "http://localhost:3000")).toBe("http://localhost:3000");
  });

  it("未設定ならフロント自身のオリジンを使う", () => {
    expect(resolveTileBaseUrl(undefined, "http://localhost:3000")).toBe("http://localhost:3000");
  });

  it("オリジンが無い実行（SSR）では空文字を返し、相対パスのまま組み立てさせる", () => {
    expect(resolveTileBaseUrl(undefined, null)).toBe("");
  });
});
