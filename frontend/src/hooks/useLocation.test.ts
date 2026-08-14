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

  it("手動入力の緯度経度をhandleManualSubmitで反映する", () => {
    const { result } = renderHook(() => useLocation());

    act(() => {
      result.current.setManualLat("35.0");
      result.current.setManualLng("135.0");
    });
    act(() => {
      result.current.handleManualSubmit({ preventDefault: () => {} } as React.FormEvent);
    });

    expect(result.current.location).toEqual({ latitude: 35.0, longitude: 135.0 });
    expect(result.current.locationSource).toBe("manual");
  });
});
