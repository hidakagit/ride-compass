// @vitest-environment node
/**
 * `lib/tileBaseUrl.ts`——地図タイルを取りに行くオリジンの決め方。
 *
 * 決め方は環境変数と画面のオリジンを引数で受ける`resolveTileBaseUrl`にあり、それを呼ぶ。環境変数を読むだけの
 * `tileBaseUrl`は呼ばない——`NEXT_PUBLIC_TILE_BASE_URL`はほかの実装も読み、テストで立てると並行する別のファイルの
 * 期待値が変わる（testing.md「パターン7」）。
 *
 * ここで見ないもの:
 * - オリジンをタイルのURLへ付けること → 使う側（`features/map/layers/jmaDelivery.test.ts`・`features/map/regionApi.test.ts`）
 */
import { describe, expect, it } from "vitest";

import { resolveTileBaseUrl } from "@/lib/tileBaseUrl";

describe("resolveTileBaseUrl", () => {
  it.each([
    ["末尾の/が無い", "https://tiles.example.com", "https://tiles.example.com"],
    ["末尾の/が1つ", "https://tiles.example.com/", "https://tiles.example.com"],
    ["末尾の/が続く", "https://tiles.example.com//", "https://tiles.example.com"],
  ])("設定があれば、画面のオリジンより設定を使い、末尾の/を外す（%s）", (_scene, configured, expected) => {
    expect(resolveTileBaseUrl(configured, "https://app.example.com")).toBe(expected);
  });

  it.each([undefined, ""])("設定が無ければ（%j）、画面のオリジンを使う", (configured) => {
    expect(resolveTileBaseUrl(configured, "https://app.example.com")).toBe("https://app.example.com");
  });

  it("設定も画面のオリジンも無ければ（サーバー側の描画）、空文字を返す", () => {
    expect(resolveTileBaseUrl(undefined, null)).toBe("");
  });
});
