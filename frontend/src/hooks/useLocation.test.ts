import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation } from "./useLocation";

type SuccessCallback = (position: GeolocationPosition) => void;
type ErrorCallback = (error: GeolocationPositionError) => void;

function makePosition(latitude: number, longitude: number): GeolocationPosition {
  return {
    coords: {
      latitude,
      longitude,
      accuracy: 1,
      altitude: null,
      altitudeAccuracy: null,
      heading: null,
      speed: null,
      toJSON: () => ({}),
    },
    timestamp: Date.now(),
    toJSON: () => ({}),
  } as GeolocationPosition;
}

describe("useLocation", () => {
  let calls: { success: SuccessCallback; error: ErrorCallback }[];

  beforeEach(() => {
    calls = [];
    Object.defineProperty(global.navigator, "geolocation", {
      value: {
        getCurrentPosition: vi.fn((success: SuccessCallback, error: ErrorCallback) => {
          calls.push({ success, error });
        }),
      },
      configurable: true,
    });
  });

  // マウント時の自動取得は最大8秒かかりうる（backend/実機のGPS事情）。ユーザーが
  // 「現在地に移動」ボタンを押して発行した新しいリクエストの結果を、後から遅れて
  // 返ってきたマウント時取得の結果が黙って上書きしてしまわないことを検証する。
  it("先に発行されたが後から解決するマウント時取得が、後発のhandleLocateMeの結果を上書きしない", () => {
    const { result } = renderHook(() => useLocation());

    // マウント時の自動取得（1件目）が発行され、まだ未解決
    expect(calls).toHaveLength(1);

    // ユーザーがボタンを押して2件目のリクエストを発行
    act(() => {
      result.current.handleLocateMe();
    });
    expect(calls).toHaveLength(2);

    // 2件目（ボタン操作）が先に解決する
    act(() => {
      calls[1].success(makePosition(34.6937, 135.5023));
    });
    expect(result.current.location).toEqual({ latitude: 34.6937, longitude: 135.5023 });
    expect(result.current.locationSource).toBe("geolocation");

    // 1件目（マウント時取得）が遅れて解決しても、古いリクエストの結果は反映されない
    act(() => {
      calls[0].success(makePosition(1, 1));
    });
    expect(result.current.location).toEqual({ latitude: 34.6937, longitude: 135.5023 });
  });

  it("後発のhandleLocateMeが失敗しても、先発の古いリクエストの失敗コールバックが結果を上書きしない", () => {
    const { result } = renderHook(() => useLocation());

    act(() => {
      result.current.handleLocateMe();
    });
    act(() => {
      calls[1].success(makePosition(34.6937, 135.5023));
    });
    expect(result.current.location).toEqual({ latitude: 34.6937, longitude: 135.5023 });

    // 古いマウント時取得が遅れて「失敗」で解決しても、既に確定した新しい位置情報や
    // locateErrorは変化しない
    act(() => {
      calls[0].error({ code: 1, message: "denied" } as GeolocationPositionError);
    });
    expect(result.current.location).toEqual({ latitude: 34.6937, longitude: 135.5023 });
    expect(result.current.locateError).toBeNull();
  });

  it("位置情報APIが無い端末ではhandleLocateMeがエラーメッセージを表示する", () => {
    Object.defineProperty(global.navigator, "geolocation", { value: undefined, configurable: true });
    const { result } = renderHook(() => useLocation());

    act(() => {
      result.current.handleLocateMe();
    });
    expect(result.current.locateError).toBe("この端末では位置情報を取得できません。");
    expect(result.current.locating).toBe(false);
  });

  // 改善計画T366: 地図タップによる出発地点の手動指定。
  describe("setManualLocation", () => {
    it("locationとlocationSourceを更新する", () => {
      const { result } = renderHook(() => useLocation());

      act(() => {
        result.current.setManualLocation({ latitude: 35.6812, longitude: 139.7671 });
      });

      expect(result.current.location).toEqual({ latitude: 35.6812, longitude: 139.7671 });
      expect(result.current.locationSource).toBe("manual");
    });

    it("マウント時の自動取得がまだ未解決のまま手動指定した後、遅れて解決しても手動指定を上書きしない", () => {
      const { result } = renderHook(() => useLocation());
      expect(calls).toHaveLength(1); // マウント時取得はまだ未解決

      act(() => {
        result.current.setManualLocation({ latitude: 35.6812, longitude: 139.7671 });
      });

      act(() => {
        calls[0].success(makePosition(1, 1));
      });

      expect(result.current.location).toEqual({ latitude: 35.6812, longitude: 139.7671 });
      expect(result.current.locationSource).toBe("manual");
    });

    it("手動指定後にhandleLocateMeを呼ぶとgeolocationへ戻る", () => {
      const { result } = renderHook(() => useLocation());
      act(() => {
        result.current.setManualLocation({ latitude: 35.6812, longitude: 139.7671 });
      });

      act(() => {
        result.current.handleLocateMe();
      });
      act(() => {
        calls[calls.length - 1].success(makePosition(34.6937, 135.5023));
      });

      expect(result.current.location).toEqual({ latitude: 34.6937, longitude: 135.5023 });
      expect(result.current.locationSource).toBe("geolocation");
    });
  });

  describe("位置が分かっているかと、分からないことの印", () => {
    it("自動取得が決着するまでは、分かっていないが印も出さない。取れたら分かっている", () => {
      const { result } = renderHook(() => useLocation());
      expect(result.current.locationKnown).toBe(false);
      expect(result.current.locationFailure).toBeNull();

      act(() => {
        calls[0].success(makePosition(34.6937, 135.5023));
      });

      expect(result.current.locationKnown).toBe(true);
      expect(result.current.locationFailure).toBeNull();
    });

    it("自動取得に失敗したら印を出し、印から取り直して取れたら消える", () => {
      const { result } = renderHook(() => useLocation());

      act(() => {
        calls[0].error({ code: 1, message: "denied" } as GeolocationPositionError);
      });

      expect(result.current.locationKnown).toBe(false);
      expect(result.current.locationFailure).toMatchObject({ id: "location", label: "現在地" });

      act(() => result.current.locationFailure?.onRetry?.());
      act(() => {
        calls[1].success(makePosition(34.6937, 135.5023));
      });

      expect(result.current.locationKnown).toBe(true);
      expect(result.current.locationFailure).toBeNull();
    });

    it("位置情報APIが無い端末では（マイクロタスク経由で）待たせず印を出す", async () => {
      Object.defineProperty(global.navigator, "geolocation", { value: undefined, configurable: true });
      const { result } = renderHook(() => useLocation());

      await act(async () => {
        await Promise.resolve();
      });

      expect(result.current.locationFailure).toMatchObject({ id: "location" });
    });

    it("自動取得の決着より先に手で置いた位置は、分かっている位置になる", () => {
      const { result } = renderHook(() => useLocation());

      act(() => result.current.setManualLocation({ latitude: 34.6937, longitude: 135.5023 }));

      expect(result.current.locationKnown).toBe(true);
      expect(result.current.locationFailure).toBeNull();
    });
  });
});
