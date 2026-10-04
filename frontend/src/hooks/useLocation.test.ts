/**
 * 位置の取得と保持（`hooks/useLocation.ts: useLocation`）——マウント時に自動で取り、「現在地に移動」で取り直し、
 * 手で地点を決められる。並走する要求は最後に出したものだけを反映する。位置が分からないことの印の項目は、
 * 最初の取得が決着するまで出さない。
 *
 * ここで見ないもの:
 * - 位置が分からない間に天候・警報を取らないこと、印の項目をヘッダーに並べること → `app/page.test.tsx`
 *
 * 差し替えたもの: 位置情報の取得（`navigator.geolocation`。テスト環境に無いブラウザの機能）。要求ごとに、
 * テストが決めた時に成功か失敗で返す。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Coordinates } from "@/types/route";

import { useLocation } from "./useLocation";

interface PendingRequest {
  succeed: (point: Coordinates) => void;
  fail: () => void;
}

const HERE: Coordinates = { latitude: 35.6812, longitude: 139.7671 };
const THERE: Coordinates = { latitude: 34.7025, longitude: 135.4959 };
const PICKED: Coordinates = { latitude: 43.0687, longitude: 141.3508 };

let requests: PendingRequest[];

function installGeolocation() {
  requests = [];
  const geolocation = {
    getCurrentPosition(onSuccess: PositionCallback, onError: PositionErrorCallback) {
      requests.push({
        succeed: (point) =>
          act(() =>
            onSuccess({ coords: { latitude: point.latitude, longitude: point.longitude } } as GeolocationPosition),
          ),
        fail: () => act(() => onError({ code: 1, message: "denied" } as GeolocationPositionError)),
      });
    },
  };
  Object.defineProperty(navigator, "geolocation", { value: geolocation, configurable: true });
}

function removeGeolocation() {
  Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });
}

beforeEach(() => {
  installGeolocation();
});

afterEach(() => {
  removeGeolocation();
});

describe("マウント時の自動取得", () => {
  it("決着するまでは初期地点で、位置は分からないが印の項目も出さない", () => {
    const { result } = renderHook(() => useLocation());

    expect(requests).toHaveLength(1);
    expect(result.current.locationSource).toBe("default");
    expect(result.current.locationKnown).toBe(false);
    expect(result.current.locationFailure).toBeNull();
    expect(result.current.locating).toBe(false);
    expect(result.current.locateError).toBeNull();
  });

  it("取れたらその位置になり、位置が分かっている", () => {
    const { result } = renderHook(() => useLocation());

    requests[0].succeed(HERE);

    expect(result.current.location).toEqual(HERE);
    expect(result.current.locationSource).toBe("geolocation");
    expect(result.current.locationKnown).toBe(true);
    expect(result.current.locationFailure).toBeNull();
  });

  it("失敗したら初期地点のまま、文は出さずに印の項目を出し、その再試行は取り直しになる", () => {
    const { result } = renderHook(() => useLocation());
    const initial = result.current.location;

    requests[0].fail();

    expect(result.current.location).toEqual(initial);
    expect(result.current.locationKnown).toBe(false);
    expect(result.current.locateError).toBeNull();
    expect(result.current.locationFailure).toMatchObject({ id: "location", label: "現在地" });
    expect(result.current.locationFailure?.onRetry).toBe(result.current.handleLocateMe);
  });

  it("位置情報の無い端末では、問い合わせずに、描いた後で印の項目を出す", async () => {
    removeGeolocation();

    const { result } = renderHook(() => useLocation());

    expect(result.current.locationFailure).toBeNull();
    await waitFor(() => expect(result.current.locationFailure).toMatchObject({ id: "location" }));
    expect(result.current.locateError).toBeNull();
  });
});

describe("「現在地に移動」の取り直し", () => {
  it("取っている間は取得中で、取れたらその位置になる", () => {
    const { result } = renderHook(() => useLocation());
    requests[0].fail();

    act(() => result.current.handleLocateMe());

    expect(result.current.locating).toBe(true);
    requests[1].succeed(HERE);
    expect(result.current.locating).toBe(false);
    expect(result.current.location).toEqual(HERE);
    expect(result.current.locationKnown).toBe(true);
    expect(result.current.locateError).toBeNull();
    expect(result.current.locationFailure).toBeNull();
  });

  it("失敗したら取得中を下ろして文を出し、次に押すと文を消してから取り直す", () => {
    const { result } = renderHook(() => useLocation());
    requests[0].succeed(HERE);

    act(() => result.current.handleLocateMe());
    requests[1].fail();

    expect(result.current.locating).toBe(false);
    expect(result.current.locateError).toBe(
      "現在地を取得できませんでした。位置情報の利用が許可されているかご確認ください。",
    );
    expect(result.current.location).toEqual(HERE);

    act(() => result.current.handleLocateMe());
    expect(result.current.locateError).toBeNull();
    expect(result.current.locating).toBe(true);
  });

  it("位置情報の無い端末では、取得中にせず文を出す", () => {
    removeGeolocation();
    const { result } = renderHook(() => useLocation());

    act(() => result.current.handleLocateMe());

    expect(result.current.locating).toBe(false);
    expect(result.current.locateError).toBe("この端末では位置情報を取得できません。");
  });

  it("自動取得より後に出した取り直しの結果を、遅れて返った自動取得が上書きしない", () => {
    const { result } = renderHook(() => useLocation());
    act(() => result.current.handleLocateMe());

    requests[1].succeed(HERE);
    requests[0].succeed(THERE);

    expect(result.current.location).toEqual(HERE);
  });

  it("取り直しの失敗を、遅れて返った自動取得の失敗が打ち消さない", () => {
    const { result } = renderHook(() => useLocation());
    act(() => result.current.handleLocateMe());

    requests[1].fail();
    requests[0].fail();

    expect(result.current.locateError).toBe(
      "現在地を取得できませんでした。位置情報の利用が許可されているかご確認ください。",
    );
  });

  it("自動取得の決着より先に取り直しが失敗したら、自動取得を待たずに印の項目を出す", () => {
    const { result } = renderHook(() => useLocation());
    act(() => result.current.handleLocateMe());

    requests[1].fail();

    expect(result.current.locationFailure).toMatchObject({ id: "location" });
  });
});

describe("手で地点を決める", () => {
  it("その地点になり、位置が分かっている。取得中と文は下ろす", () => {
    const { result } = renderHook(() => useLocation());
    requests[0].succeed(HERE);
    act(() => result.current.handleLocateMe());
    requests[1].fail();
    act(() => result.current.handleLocateMe());

    act(() => result.current.setManualLocation(PICKED));

    expect(result.current.location).toEqual(PICKED);
    expect(result.current.locationSource).toBe("manual");
    expect(result.current.locationKnown).toBe(true);
    expect(result.current.locating).toBe(false);
    expect(result.current.locateError).toBeNull();
  });

  it("自動取得の決着より先に決めると、位置が分かっていて印の項目は出さない", () => {
    const { result } = renderHook(() => useLocation());

    act(() => result.current.setManualLocation(PICKED));

    expect(result.current.locationKnown).toBe(true);
    expect(result.current.locationFailure).toBeNull();
  });

  it("まだ返っていない取得は、後から返っても決めた地点を上書きしない", () => {
    const { result } = renderHook(() => useLocation());
    act(() => result.current.handleLocateMe());

    act(() => result.current.setManualLocation(PICKED));
    requests[0].succeed(HERE);
    requests[1].fail();

    expect(result.current.location).toEqual(PICKED);
    expect(result.current.locationSource).toBe("manual");
    expect(result.current.locateError).toBeNull();
  });

  it("決めた後に取り直すと、取れた位置へ戻る", () => {
    const { result } = renderHook(() => useLocation());
    act(() => result.current.setManualLocation(PICKED));

    act(() => result.current.handleLocateMe());
    requests[1].succeed(HERE);

    expect(result.current.location).toEqual(HERE);
    expect(result.current.locationSource).toBe("geolocation");
  });
});
