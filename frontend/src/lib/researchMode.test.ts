import { beforeEach, describe, expect, it, vi } from "vitest";
import { isResearchEnabled, setResearchEnabled, subscribeResearchMode } from "./researchMode";

// debugLog.tsと同型のシングルトン＋購読モジュール（フラグは「研究機能の出し入れ」専用、
// debugLog.tsの「ログ表示」とは独立、改善計画T29）。debugLog.test.tsと同じ粒度・構成で
// window.localStorageへの永続化とlistener通知を検証する。

describe("researchMode", () => {
  beforeEach(() => {
    setResearchEnabled(false);
  });

  describe("setResearchEnabled / isResearchEnabled", () => {
    it("trueにするとisResearchEnabledがtrueになりlocalStorageに1が保存される", () => {
      setResearchEnabled(true);
      expect(isResearchEnabled()).toBe(true);
      expect(window.localStorage.getItem("ridecompass:research-enabled")).toBe("1");
    });

    it("falseにするとisResearchEnabledがfalseになりlocalStorageに0が保存される", () => {
      setResearchEnabled(true);
      setResearchEnabled(false);
      expect(isResearchEnabled()).toBe(false);
      expect(window.localStorage.getItem("ridecompass:research-enabled")).toBe("0");
    });

    it("localStorage.setItemが例外を投げても（プライベートブラウジング等）isResearchEnabledは更新される", () => {
      const spy = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
        throw new DOMException("QuotaExceededError");
      });

      expect(() => setResearchEnabled(true)).not.toThrow();
      expect(isResearchEnabled()).toBe(true);

      spy.mockRestore();
    });
  });

  describe("subscribeResearchMode", () => {
    it("setResearchEnabledでlistenerが呼ばれ、解除後は呼ばれない", () => {
      const listener = vi.fn();
      const unsubscribe = subscribeResearchMode(listener);

      setResearchEnabled(true);
      expect(listener).toHaveBeenCalledTimes(1);

      setResearchEnabled(false);
      expect(listener).toHaveBeenCalledTimes(2);

      unsubscribe();
      setResearchEnabled(true);
      expect(listener).toHaveBeenCalledTimes(2);
    });

    it("複数listenerを登録した場合は全員へ通知される", () => {
      const listenerA = vi.fn();
      const listenerB = vi.fn();
      subscribeResearchMode(listenerA);
      subscribeResearchMode(listenerB);

      setResearchEnabled(true);

      expect(listenerA).toHaveBeenCalledTimes(1);
      expect(listenerB).toHaveBeenCalledTimes(1);
    });
  });
});
