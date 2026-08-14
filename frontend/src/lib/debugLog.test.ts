import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearDebugLog,
  debugLog,
  getDebugLogEntries,
  isDebugEnabled,
  setDebugEnabled,
  subscribeDebugLog,
} from "./debugLog";

describe("debugLog", () => {
  beforeEach(() => {
    setDebugEnabled(false);
    clearDebugLog();
  });

  describe("setDebugEnabled / isDebugEnabled", () => {
    it("trueにするとisDebugEnabledがtrueになりlocalStorageに1が保存される", () => {
      setDebugEnabled(true);
      expect(isDebugEnabled()).toBe(true);
      expect(window.localStorage.getItem("ridecompass:debug-enabled")).toBe("1");
    });

    it("falseにするとisDebugEnabledがfalseになりlocalStorageに0が保存される", () => {
      setDebugEnabled(true);
      setDebugEnabled(false);
      expect(isDebugEnabled()).toBe(false);
      expect(window.localStorage.getItem("ridecompass:debug-enabled")).toBe("0");
    });
  });

  describe("debugLog", () => {
    it("無効時はエントリが増えずconsole.debugも呼ばれない", () => {
      const spy = vi.spyOn(console, "debug").mockImplementation(() => {});
      setDebugEnabled(false);

      debugLog("test-category", "test message", { foo: 1 });

      expect(getDebugLogEntries()).toHaveLength(0);
      expect(spy).not.toHaveBeenCalled();
      spy.mockRestore();
    });

    it("有効時はエントリが追加され、category/message/detailが保持されidが増加する", () => {
      setDebugEnabled(true);

      debugLog("cat-a", "message-a", { a: 1 });
      debugLog("cat-b", "message-b", { b: 2 });

      const entries = getDebugLogEntries();
      expect(entries).toHaveLength(2);
      expect(entries[0]).toMatchObject({ category: "cat-a", message: "message-a", detail: { a: 1 } });
      expect(entries[1]).toMatchObject({ category: "cat-b", message: "message-b", detail: { b: 2 } });
      expect(entries[1].id).toBeGreaterThan(entries[0].id);
    });
  });

  describe("subscribeDebugLog", () => {
    it("setDebugEnabled/debugLog(有効時)/clearDebugLogでlistenerが呼ばれ、解除後は呼ばれない", () => {
      const listener = vi.fn();
      const unsubscribe = subscribeDebugLog(listener);

      setDebugEnabled(true);
      expect(listener).toHaveBeenCalledTimes(1);

      debugLog("cat", "msg");
      expect(listener).toHaveBeenCalledTimes(2);

      clearDebugLog();
      expect(listener).toHaveBeenCalledTimes(3);

      unsubscribe();
      setDebugEnabled(false);
      expect(listener).toHaveBeenCalledTimes(3);
    });
  });

  describe("clearDebugLog", () => {
    it("エントリを空配列にする", () => {
      setDebugEnabled(true);
      debugLog("cat", "msg");
      expect(getDebugLogEntries().length).toBeGreaterThan(0);

      clearDebugLog();

      expect(getDebugLogEntries()).toEqual([]);
    });
  });

  describe("MAX_ENTRIES上限", () => {
    it("300件を超えて追加すると最新300件のみ残り先頭が捨てられる", () => {
      setDebugEnabled(true);

      for (let i = 0; i < 305; i++) {
        debugLog("cat", `message-${i}`);
      }

      const entries = getDebugLogEntries();
      expect(entries).toHaveLength(300);
      expect(entries[0].message).toBe("message-5");
      expect(entries[entries.length - 1].message).toBe("message-304");
    });
  });
});
