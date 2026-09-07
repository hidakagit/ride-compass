import { afterEach, describe, expect, it, vi } from "vitest";
import { readStoredValue, writeStoredValue } from "./safeStorage";

// 検証の主眼は「localStorageを触れない環境で例外を外へ出さないこと」。サイトデータを
// 全面ブロックした環境ではgetItem/setItemではなく`window.localStorage`のゲッター自体が
// SecurityErrorを投げるため、両方の投げ方を再現する。
//
// jsdomのlocalStorageはProxy越しのため`vi.restoreAllMocks()`ではスパイが戻らない。
// 各テストが自分で張ったスパイをmockRestore()する（researchMode.test.tsと同じ形）。

function spyOnLocalStorageGetter() {
  return vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new DOMException("The operation is insecure.", "SecurityError");
  });
}

describe("safeStorage", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  describe("readStoredValue", () => {
    it("保存済みの値を返す", () => {
      window.localStorage.setItem("ridecompass:test", "1");
      expect(readStoredValue("ridecompass:test")).toBe("1");
    });

    it("未保存のキーはnullを返す", () => {
      expect(readStoredValue("ridecompass:absent")).toBeNull();
    });

    it("localStorageのゲッターがSecurityErrorを投げてもnullを返す（モジュール評価時に落ちない）", () => {
      const spy = spyOnLocalStorageGetter();

      expect(() => readStoredValue("ridecompass:test")).not.toThrow();
      expect(readStoredValue("ridecompass:test")).toBeNull();

      spy.mockRestore();
    });

    it("getItemが投げてもnullを返す", () => {
      const spy = vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
        throw new DOMException("SecurityError");
      });

      expect(readStoredValue("ridecompass:test")).toBeNull();

      spy.mockRestore();
    });
  });

  describe("writeStoredValue", () => {
    it("値を保存する", () => {
      writeStoredValue("ridecompass:test", "0");
      expect(window.localStorage.getItem("ridecompass:test")).toBe("0");
    });

    it("localStorageのゲッターがSecurityErrorを投げても例外を外へ出さない", () => {
      const spy = spyOnLocalStorageGetter();

      expect(() => writeStoredValue("ridecompass:test", "1")).not.toThrow();

      spy.mockRestore();
    });

    it("setItemが投げても例外を外へ出さない（容量超過・プライベートブラウジング）", () => {
      const spy = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
        throw new DOMException("QuotaExceededError");
      });

      expect(() => writeStoredValue("ridecompass:test", "1")).not.toThrow();

      spy.mockRestore();
    });
  });
});
