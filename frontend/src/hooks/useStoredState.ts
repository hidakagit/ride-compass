"use client";

import { useCallback, useRef, useState } from "react";
import { useIsomorphicLayoutEffect } from "./useIsomorphicLayoutEffect";

interface UseStoredStateOptions<T> {
  /** 保存する文字列への変換（JSON化するかは呼び出し側が選ぶ。生の文字列で保存しているキーと形を揃えるため）。 */
  serialize: (value: T) => string;
  /** 保存文字列からTへの変換。不正・旧形式の値はnullを返す（デフォルト値のまま扱われる）。 */
  deserialize: (raw: string) => T | null;
  /** falseならsetterは保存せず、呼び出し側が戻り値の3番目（commit）で保存する（例: ドラッグ中は保存せず確定時だけ）。 */
  autoSave?: boolean;
  /** 変わるたびに、その時点のdeserializeで読み直す（省略時はマウントの1回だけ）。deserializeが実行時に届く一覧
   * （軸カタログ等）で復元する値を決めるとき、届いたことを渡す。 */
  reloadKey?: unknown;
}

// localStorageへ保存し、読み込み直しても復元するuseState。
//
// 復元は初期化子ではなくマウント後のlayout effectで行う（初期化子で読むとSSRのHTMLとずれる）。localStorageが使えない
// 環境では読み書きの失敗を既定値として握りつぶす。保存はeffectではなくsetterのたびに書く——effectで保存すると、
// StrictModeの再マウントで「復元前の初期値の保存」が割り込み、保存済みの設定を既定値で上書きする。
export function useStoredState<T>(
  key: string,
  defaultValue: T,
  { serialize, deserialize, autoSave = true, reloadKey }: UseStoredStateOptions<T>,
): [T, (value: T | ((prev: T) => T)) => void, (value: T) => void] {
  const [value, setValue] = useState(defaultValue);
  // serializeは描画ごとに別の関数で届くが、commit・setterの参照は安定させたい（ほかの依存に使われる）。
  const serializeRef = useRef(serialize);
  useIsomorphicLayoutEffect(() => {
    serializeRef.current = serialize;
  });

  // deserializeはrefへ退避しない（reloadKeyが変わったとき、その時点のdeserializeで読み直す）。
  useIsomorphicLayoutEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw == null) {
        setValue(defaultValue);
        return;
      }
      const parsed = deserialize(raw);
      setValue(parsed != null ? parsed : defaultValue);
    } catch {
      setValue(defaultValue);
    }
    // defaultValueは依存に入れない（呼び出し側が描画ごとに新しいリテラルを渡すため、入れると読み直しが止まらない）。
  }, [key, reloadKey]);

  const commit = useCallback(
    (next: T) => {
      try {
        window.localStorage.setItem(key, serializeRef.current(next));
      } catch {}
    },
    [key],
  );

  const setStoredValue = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (prev: T) => T)(prev) : next;
        if (autoSave) commit(resolved);
        return resolved;
      });
    },
    [autoSave, commit],
  );

  return [value, setStoredValue, commit];
}

// JSONで保存するuseState（壊れた保存値は既定値）。
export function useStoredJsonState<T>(
  key: string,
  defaultValue: T,
): [T, (value: T | ((prev: T) => T)) => void, (value: T) => void] {
  return useStoredState<T>(key, defaultValue, {
    serialize: (v) => JSON.stringify(v),
    deserialize: (raw) => {
      try {
        return JSON.parse(raw) as T;
      } catch {
        return null;
      }
    },
  });
}

// 真偽値1つを保存するuseState。**保存値の型まで確かめる**（JSONのままだと`"3"`や`"null"`が流れ込む）。
export function useStoredBooleanState(
  key: string,
  defaultValue: boolean,
): [boolean, (value: boolean | ((prev: boolean) => boolean)) => void, (value: boolean) => void] {
  return useStoredState<boolean>(key, defaultValue, {
    serialize: (v) => JSON.stringify(v),
    deserialize: (raw) => {
      try {
        const parsed = JSON.parse(raw);
        return typeof parsed === "boolean" ? parsed : null;
      } catch {
        return null;
      }
    },
  });
}
