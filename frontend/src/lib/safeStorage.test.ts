/**
 * `lib/safeStorage.ts`——localStorageの読み書きを、使えない環境でも投げない形にしたもの。
 *
 * 使えない環境は2つ: サイトデータを全面的に止めたブラウザ（`window.localStorage`を読むだけで投げる。保存の上限を
 * 超えたときは書き込みだけが投げる）と、サーバー側の描画（`window`が無い）。どちらもテスト環境には無いので、
 * localStorageの口と`window`を差し替えて作る。
 *
 * ここで見ないもの:
 * - 読んだ値で初期値を決めるシングルトン → `lib/debugLog.test.ts`・`lib/researchMode.test.ts`
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { readStoredValue, writeStoredValue } from "@/lib/safeStorage";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function blockSiteData(): void {
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new DOMException("The operation is insecure.", "SecurityError");
  });
}

describe("使える環境", () => {
  it("書いた値を読める", () => {
    writeStoredValue("key_a", "1");

    expect(readStoredValue("key_a")).toBe("1");
  });

  it("書いていない鍵はnullを返す", () => {
    expect(readStoredValue("key_a")).toBeNull();
  });
});

describe("サイトデータを止めたブラウザ", () => {
  it("読むと、未保存と同じnullを返す", () => {
    window.localStorage.setItem("key_a", "1");
    blockSiteData();

    expect(readStoredValue("key_a")).toBeNull();
  });

  it("書いても投げない", () => {
    blockSiteData();

    expect(() => writeStoredValue("key_a", "1")).not.toThrow();
  });
});

describe("保存の上限を超えたブラウザ", () => {
  it("書いても投げない", () => {
    const setItem = vi.fn(() => {
      throw new DOMException("The quota has been exceeded.", "QuotaExceededError");
    });
    vi.spyOn(window, "localStorage", "get").mockReturnValue({ setItem } as unknown as Storage);

    expect(() => writeStoredValue("key_a", "1")).not.toThrow();
    expect(setItem).toHaveBeenCalledWith("key_a", "1");
  });
});

describe("サーバー側の描画（windowが無い）", () => {
  it("読むとnullを返し、書いても投げない", () => {
    vi.stubGlobal("window", undefined);

    expect(readStoredValue("key_a")).toBeNull();
    expect(() => writeStoredValue("key_a", "1")).not.toThrow();
  });
});
