import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setResearchEnabled } from "@/lib/researchMode";
import { useResearchEnabled } from "./useResearchMode";

// lib/researchMode.tsのuseSyncExternalStoreラッパー。useDebugLog.test.tsと同じ粒度で
// 初期値の反映とsetResearchEnabled変更への追従を検証する。

describe("useResearchMode", () => {
  beforeEach(() => {
    setResearchEnabled(false);
  });

  describe("useResearchEnabled", () => {
    it("初期状態はisResearchEnabledの値を反映する", () => {
      const { result } = renderHook(() => useResearchEnabled());
      expect(result.current).toBe(false);
    });

    it("setResearchEnabledの変更に追従する", () => {
      const { result } = renderHook(() => useResearchEnabled());

      act(() => {
        setResearchEnabled(true);
      });
      expect(result.current).toBe(true);

      act(() => {
        setResearchEnabled(false);
      });
      expect(result.current).toBe(false);
    });

    it("マウント前にtrueへ変更されていた場合も初期値へ反映する", () => {
      setResearchEnabled(true);
      const { result } = renderHook(() => useResearchEnabled());
      expect(result.current).toBe(true);
    });
  });
});
