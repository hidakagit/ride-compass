/**
 * 端末に保存して、開き直しても戻る状態（`hooks/useStoredState.ts`）——保存値を読んで復元し、変えるたびに保存する。
 * 読めない・壊れた保存値は既定値として扱い、保存できない端末でも状態は変わる。
 * JSON で保存する形（`useStoredJsonState`）と、真偽値だけを受け入れる形（`useStoredBooleanState`）も、ここで見る。
 *
 * ここで見ないもの:
 * - どのキーに何を保存するか・どう復元するか（変換の中身） → 呼び出し側
 *
 * 差し替えたもの: 保存の読み書きが例外を投げる端末（`window.localStorage` のゲッターを、読むか書くかが例外を投げる
 * 保存へ）。それ以外の保存はテスト環境の `localStorage` を本物のまま使う。
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useStoredBooleanState, useStoredJsonState, useStoredState } from "./useStoredState";

const KEY = "stored-state-test";

/** 文字列をそのまま保存し、`ok:` で始まるものだけを読む変換。 */
const PREFIXED = {
  serialize: (value: string) => `ok:${value}`,
  deserialize: (raw: string) => (raw.startsWith("ok:") ? raw.slice(3) : null),
};

/** 読むか書くかが例外を投げる端末にする。もう片方はテスト環境の保存へ渡す。 */
function breakStorage(method: "getItem" | "setItem") {
  const real = window.localStorage;
  const storage = {
    getItem: (key: string) => real.getItem(key),
    setItem: (key: string, value: string) => real.setItem(key, value),
    [method]: () => {
      throw new Error("storage unavailable");
    },
  };
  vi.spyOn(window, "localStorage", "get").mockReturnValue(storage as unknown as Storage);
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("useStoredState", () => {
  it("保存が無ければ既定値を返す", () => {
    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    expect(result.current[0]).toBe("default");
  });

  it("保存があれば、変換して読んだ値へ戻す", () => {
    window.localStorage.setItem(KEY, "ok:saved");

    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    expect(result.current[0]).toBe("saved");
  });

  it("変換が読めない（null を返す）保存値は、既定値として扱う", () => {
    window.localStorage.setItem(KEY, "broken");

    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    expect(result.current[0]).toBe("default");
  });

  it("保存を読めない端末では、保存があっても既定値を返す", () => {
    window.localStorage.setItem(KEY, "ok:saved");
    breakStorage("getItem");

    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    expect(result.current[0]).toBe("default");
  });

  it("値を渡して変えると、状態が変わり、変換した文字列で保存する", () => {
    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    act(() => result.current[1]("next"));

    expect(result.current[0]).toBe("next");
    expect(window.localStorage.getItem(KEY)).toBe("ok:next");
  });

  it("関数を渡して変えると、今の値から作った値になり、それを保存する", () => {
    window.localStorage.setItem(KEY, "ok:a");
    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    act(() => result.current[1]((prev) => `${prev}b`));

    expect(result.current[0]).toBe("ab");
    expect(window.localStorage.getItem(KEY)).toBe("ok:ab");
  });

  it("保存できない端末でも、状態は変わる", () => {
    breakStorage("setItem");
    const { result } = renderHook(() => useStoredState(KEY, "default", PREFIXED));

    act(() => result.current[1]("next"));

    expect(result.current[0]).toBe("next");
    vi.restoreAllMocks();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("保存には、変えた時点で渡されている変換を使う", () => {
    const { result, rerender } = renderHook(
      ({ serialize }) => useStoredState(KEY, "default", { ...PREFIXED, serialize }),
      { initialProps: { serialize: PREFIXED.serialize } },
    );

    rerender({ serialize: (value: string) => `v2:${value}` });
    act(() => result.current[1]("next"));

    expect(window.localStorage.getItem(KEY)).toBe("v2:next");
  });

  it("変える関数は、描き直しても同じものを返す（読み手が依存に使える）", () => {
    const { result, rerender } = renderHook(() => useStoredState(KEY, "default", { ...PREFIXED }));
    const first = result.current[1];

    rerender();

    expect(result.current[1]).toBe(first);
  });

  it("キーが変わると、新しいキーの保存を読み、以後はそのキーへ保存する", () => {
    window.localStorage.setItem("key-b", "ok:b");
    const { result, rerender } = renderHook(({ key }) => useStoredState(key, "default", PREFIXED), {
      initialProps: { key: "key-a" },
    });

    rerender({ key: "key-b" });
    expect(result.current[0]).toBe("b");

    act(() => result.current[1]("next"));
    expect(window.localStorage.getItem("key-b")).toBe("ok:next");
    expect(window.localStorage.getItem("key-a")).toBeNull();
  });

  it.each([
    ["保存が無い", () => {}],
    ["保存が読めない", () => window.localStorage.setItem("key-b", "broken")],
    ["保存を読めない端末", () => breakStorage("getItem")],
  ])("キーが変わって新しいキーの%sときは、前のキーの値を引きずらず既定値へ戻る", (_, arrange) => {
    window.localStorage.setItem("key-a", "ok:a");
    const { result, rerender } = renderHook(({ key }) => useStoredState(key, "default", PREFIXED), {
      initialProps: { key: "key-a" },
    });
    expect(result.current[0]).toBe("a");

    arrange();
    rerender({ key: "key-b" });

    expect(result.current[0]).toBe("default");
  });

  it("読み直しの合図が変わると、その時点の変換で読み直す", () => {
    window.localStorage.setItem(KEY, "axis_b");
    const knownOf = (known: string[]) => ({
      serialize: (value: string) => value,
      deserialize: (raw: string) => (known.includes(raw) ? raw : null),
    });
    const { result, rerender } = renderHook(
      ({ known }) => useStoredState(KEY, "default", { ...knownOf(known), reloadKey: known.length }),
      { initialProps: { known: ["axis_a"] } },
    );
    expect(result.current[0]).toBe("default");

    rerender({ known: ["axis_a", "axis_b"] });

    expect(result.current[0]).toBe("axis_b");
  });

  it("読み直しの合図が同じなら、描き直しのたびに変換や既定値が新しく渡されても読み直さない", () => {
    window.localStorage.setItem(KEY, "ok:saved");
    let renders = 0;
    const { result, rerender } = renderHook(() =>
      useStoredState(KEY, `default-${++renders}`, { ...PREFIXED, deserialize: (raw) => PREFIXED.deserialize(raw) }),
    );
    window.localStorage.setItem(KEY, "ok:written-elsewhere");

    rerender();

    expect(result.current[0]).toBe("saved");
  });
});

describe("useStoredJsonState", () => {
  it("JSON で保存し、開き直すと同じ値へ戻る", () => {
    const first = renderHook(() => useStoredJsonState(KEY, { size: 1 }));
    act(() => first.result.current[1]({ size: 3 }));
    first.unmount();

    const second = renderHook(() => useStoredJsonState(KEY, { size: 1 }));

    expect(second.result.current[0]).toEqual({ size: 3 });
  });

  it("JSON として読めない保存値は、既定値として扱う", () => {
    window.localStorage.setItem(KEY, "{broken");

    const { result } = renderHook(() => useStoredJsonState(KEY, { size: 1 }));

    expect(result.current[0]).toEqual({ size: 1 });
  });
});

describe("useStoredBooleanState", () => {
  it("真偽値で保存し、開き直すと同じ値へ戻る", () => {
    const first = renderHook(() => useStoredBooleanState(KEY, false));
    act(() => first.result.current[1](true));
    first.unmount();

    const second = renderHook(() => useStoredBooleanState(KEY, false));

    expect(second.result.current[0]).toBe(true);
  });

  it.each(["0", '"true"', "{broken"])("真偽値でない保存値 %s は、既定値として扱う", (raw) => {
    window.localStorage.setItem(KEY, raw);

    const { result } = renderHook(() => useStoredBooleanState(KEY, true));

    expect(result.current[0]).toBe(true);
  });
});
