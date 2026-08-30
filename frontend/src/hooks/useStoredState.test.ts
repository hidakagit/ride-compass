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

  // 実バグ修正の回帰テスト（デッドコード監査、2026-08-25）: app/page.tsxのlayerVisibility
  // 永続化ホワイトリスト静的固定バグ。復元対象キー集合が実行時カタログ（axisCatalog.
  // rampAxes等）に依存するとき、そのカタログのフェッチが完了する前（マウント直後）にしか
  // 復元処理が走らないと、フェッチ完了後に初めて存在が分かる動的キー（軸スタジオ公開軸等）の
  // 保存値が黙って無視される。reloadKeyに「カタログがフェッチ済みか」を渡すことで、
  // フェッチ完了時に復元処理を再実行し、その時点の最新のdeserializeクロージャ
  // （動的キー集合を認識できる）で再度localStorageから読み直せることを確認する。
  it("reloadKeyが変化すると、その時点の最新のdeserializeで復元処理を再実行する", () => {
    window.localStorage.setItem("k3", JSON.stringify({ fixed: true, dynamic: true }));

    let loaded = false;
    const deserialize = (raw: string): Record<string, boolean> | null => {
      try {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        // 未フェッチ時は固定キーのみ、フェッチ完了後は動的キーも走査する
        // （page.tsx: layerVisibilityのdeserializeと同じ形）。
        const keys = loaded ? ["fixed", "dynamic"] : ["fixed"];
        const next: Record<string, boolean> = { fixed: false, dynamic: false };
        for (const key of keys) {
          if (typeof parsed[key] === "boolean") next[key] = parsed[key];
        }
        return next;
      } catch {
        return null;
      }
    };

    const { result, rerender } = renderHook(
      ({ reloadKey }: { reloadKey: boolean }) =>
        useStoredState("k3", { fixed: false, dynamic: false }, {
          serialize: (v) => JSON.stringify(v),
          deserialize,
          reloadKey,
        }),
      { initialProps: { reloadKey: false } },
    );

    // マウント時点（reloadKey=false・loaded=false相当）ではdynamicキーは復元されない。
    expect(result.current[0]).toEqual({ fixed: true, dynamic: false });

    // カタログ取得完了に相当する変化（reloadKeyの値を変える）。
    loaded = true;
    rerender({ reloadKey: true });

    expect(result.current[0]).toEqual({ fixed: true, dynamic: true });
  });

  // 改善計画T470: keyが動的に変わるケース（現状の呼び出し側はいずれも静的keyのため
  // 未発生だが、将来追加されうる）で、新しいkeyに保存値が無いと前のkeyで復元した値が
  // 残り続けてしまう不整合の回帰テスト。
  it("keyが変化し、新しいkeyに保存値が無い場合はdefaultValueへ戻る（前のkeyの値を引きずらない）", () => {
    window.localStorage.setItem("k5-a", "42");

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useStoredState(key, 1, jsonOptions),
      { initialProps: { key: "k5-a" } },
    );
    expect(result.current[0]).toBe(42);

    rerender({ key: "k5-b" }); // k5-bには保存値が無い

    expect(result.current[0]).toBe(1);
  });

  it("keyが変化し、新しいkeyにも保存値がある場合はそちらを復元する", () => {
    window.localStorage.setItem("k6-a", "42");
    window.localStorage.setItem("k6-b", "99");

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useStoredState(key, 1, jsonOptions),
      { initialProps: { key: "k6-a" } },
    );
    expect(result.current[0]).toBe(42);

    rerender({ key: "k6-b" });

    expect(result.current[0]).toBe(99);
  });

  it("reloadKeyを渡さない場合は従来どおり初回マウント時の1回だけ復元する", () => {
    window.localStorage.setItem("k4", "42");
    const { result, rerender } = renderHook(() => useStoredState("k4", 1, jsonOptions));
    expect(result.current[0]).toBe(42);

    // マウント後に保存値を書き換えても、reloadKey省略時は再復元されない（元の挙動）。
    window.localStorage.setItem("k4", "100");
    rerender();
    expect(result.current[0]).toBe(42);
  });
});
