import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useRouteFormSubmit, isMaxRoutesRelevant } from "./useRouteFormSubmit";
import type { DestinationButtonState, RouteMode } from "./RouteForm";

function setup(overrides: {
  distance?: string;
  maxRoutes?: string;
  routeMode?: RouteMode;
  waypointCount?: number;
  destinationState?: DestinationButtonState;
  onGenerate?: (distanceKm: number) => void;
}) {
  const onGenerate = overrides.onGenerate ?? vi.fn();
  const { result } = renderHook(() =>
    useRouteFormSubmit({
      distance: overrides.distance ?? "30",
      maxRoutes: overrides.maxRoutes ?? "8",
      routeMode: overrides.routeMode ?? "loop",
      waypointCount: overrides.waypointCount ?? 0,
      destinationState: overrides.destinationState ?? "unset",
      onGenerate,
    })
  );
  return { result, onGenerate };
}

describe("isMaxRoutesRelevant", () => {
  it("周回モードでは常にtrue", () => {
    expect(isMaxRoutesRelevant("loop", 0)).toBe(true);
    expect(isMaxRoutesRelevant("loop", 3)).toBe(true);
  });

  it("目的地モードでは経由地が無いときだけtrue", () => {
    expect(isMaxRoutesRelevant("destination", 0)).toBe(true);
    expect(isMaxRoutesRelevant("destination", 1)).toBe(false);
  });
});

describe("useRouteFormSubmit（周回モード）", () => {
  it("既定値のまま送信するとonGenerateが30(number)で呼ばれる", () => {
    const { result, onGenerate } = setup({});
    act(() => result.current.handleSubmit());

    expect(onGenerate).toHaveBeenCalledWith(30);
    expect(result.current.error).toBeNull();
  });

  it("距離が空文字だとonGenerateは呼ばれずエラーになる", () => {
    const { result, onGenerate } = setup({ distance: "" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("距離は数値で入力してください。");
  });

  it("距離が0以下だとonGenerateは呼ばれずエラーになる", () => {
    const { result, onGenerate } = setup({ distance: "0" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("距離は0より大きい値を入力してください。");
  });

  it("距離が上限(100km)を超えるとonGenerateは呼ばれずエラーになる", () => {
    const { result, onGenerate } = setup({ distance: "150" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("距離は100km以下で入力してください。");
  });

  it("候補件数が整数でないとonGenerateは呼ばれずエラーになる", () => {
    const { result, onGenerate } = setup({ maxRoutes: "2.5" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("候補件数は整数で入力してください。");
  });

  it("候補件数が範囲外(0や16)だとonGenerateは呼ばれずエラーになる", () => {
    const { result, onGenerate } = setup({ maxRoutes: "0" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("候補件数は1〜15件で入力してください。");
  });

  it("候補件数が上限(15件)ちょうどなら送信できる", () => {
    const { result, onGenerate } = setup({ maxRoutes: "15" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).toHaveBeenCalledWith(30);
  });
});

describe("useRouteFormSubmit（目的地モード）", () => {
  it("経由地・目的地とも未指定のまま送信するとエラーになりonGenerateは呼ばれない", () => {
    const { result, onGenerate } = setup({ routeMode: "destination" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("地図をタップして目的地か経由地を指定してください。");
  });

  it("destinationState=setなら送信でonGenerate(0)が呼ばれる（距離はpage.tsx側で自動算出）", () => {
    const { result, onGenerate } = setup({ routeMode: "destination", destinationState: "set" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).toHaveBeenCalledWith(0);
  });

  it("経由地が1件以上あれば目的地未設定でも送信できる（候補件数入力は無関係のため検証しない）", () => {
    const { result, onGenerate } = setup({ routeMode: "destination", waypointCount: 1 });
    act(() => result.current.handleSubmit());

    expect(onGenerate).toHaveBeenCalledWith(0);
  });

  it("経由地が無い場合は候補件数の検証が働く", () => {
    const { result, onGenerate } = setup({ routeMode: "destination", destinationState: "set", maxRoutes: "16" });
    act(() => result.current.handleSubmit());

    expect(onGenerate).not.toHaveBeenCalled();
    expect(result.current.error).toBe("候補件数は1〜15件で入力してください。");
  });
});
