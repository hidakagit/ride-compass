import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearDebugLog, debugLog, setDebugEnabled } from "@/lib/debugLog";
import { useDebugEnabled, useDebugLogEntries } from "./useDebugLog";

describe("useDebugLog", () => {
  beforeEach(() => {
    setDebugEnabled(false);
    clearDebugLog();
  });

  describe("useDebugEnabled", () => {
    it("初期状態はisDebugEnabledの値を反映する", () => {
      const { result } = renderHook(() => useDebugEnabled());
      expect(result.current).toBe(false);
    });

    it("setDebugEnabledの変更に追従する", () => {
      const { result } = renderHook(() => useDebugEnabled());

      act(() => {
        setDebugEnabled(true);
      });
      expect(result.current).toBe(true);

      act(() => {
        setDebugEnabled(false);
      });
      expect(result.current).toBe(false);
    });
  });

  describe("useDebugLogEntries", () => {
    it("debugLog呼び出し(有効時)でエントリが追加され追従する", () => {
      setDebugEnabled(true);
      const { result } = renderHook(() => useDebugLogEntries());

      expect(result.current).toHaveLength(0);

      act(() => {
        debugLog("cat", "message-1");
      });
      expect(result.current).toHaveLength(1);
      expect(result.current[0]).toMatchObject({ category: "cat", message: "message-1" });

      act(() => {
        clearDebugLog();
      });
      expect(result.current).toHaveLength(0);
    });
  });
});
