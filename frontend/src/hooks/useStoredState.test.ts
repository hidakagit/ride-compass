import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useStoredState } from "./useStoredState";

const jsonOptions = {
  serialize: (v: number) => JSON.stringify(v),
  deserialize: (raw: string): number | null => {
    try {
      const parsed = JSON.parse(raw);
      return typeof parsed === "number" ? parsed : null;
    } catch {
      return null;
    }
  },
};

describe("useStoredState", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("保存値が無ければデフォルト値のまま", () => {
    const { result } = renderHook(() => useStoredState("k", 1, jsonOptions));
    expect(result.current[0]).toBe(1);
  });

  it("マウント後に保存値を復元する", () => {
    window.localStorage.setItem("k", "42");
    const { result } = renderHook(() => useStoredState("k", 1, jsonOptions));
    expect(result.current[0]).toBe(42);
  });

  it("壊れた保存値はデフォルト値のまま(例外を投げない)", () => {
    window.localStorage.setItem("k", "not json");
    const { result } = renderHook(() => useStoredState("k", 1, jsonOptions));
    expect(result.current[0]).toBe(1);
  });

  it("setterはstateを更新しlocalStorageへ即保存する(既定autoSave=true)", () => {
    const { result } = renderHook(() => useStoredState("k", 1, jsonOptions));
    act(() => result.current[1](5));
    expect(result.current[0]).toBe(5);
    expect(window.localStorage.getItem("k")).toBe("5");
  });

  it("生文字列(JSON化しない)形式のキーも保存・復元できる(route-style-mode等と同じ形式)", () => {
    const rawOptions = {
      serialize: (v: string) => v,
      deserialize: (raw: string): string | null => (raw === "a" || raw === "b" ? raw : null),
    };
    window.localStorage.setItem("k2", "b");
    const { result } = renderHook(() => useStoredState("k2", "a", rawOptions));
    expect(result.current[0]).toBe("b");

    act(() => result.current[1]("a"));
    expect(window.localStorage.getItem("k2")).toBe("a");
  });

  it("autoSave=falseのときsetterは保存せず、commitを呼んだときだけ保存する(ドラッグ中の分離保存)", () => {
    const { result } = renderHook(() => useStoredState("k", 1, { ...jsonOptions, autoSave: false }));

    act(() => result.current[1](9));
    expect(result.current[0]).toBe(9);
    expect(window.localStorage.getItem("k")).toBeNull();

    act(() => result.current[2](9));
    expect(window.localStorage.getItem("k")).toBe("9");
  });
});
