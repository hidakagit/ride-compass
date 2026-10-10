"use client";

import { useCallback, useRef, useState } from "react";
import { readStoredValue, writeStoredValue } from "@/lib/safeStorage";
import { useIsomorphicLayoutEffect } from "./useIsomorphicLayoutEffect";

interface UseStoredStateOptions<T> {
  /** 保存する文字列への変換（JSON化するかは呼び出し側が選ぶ。生の文字列で保存しているキーと形を揃えるため）。 */
  serialize: (value: T) => string;
  /** 保存文字列からTへの変換。不正・旧形式の値はnullを返すか投げる（どちらもデフォルト値のまま扱われる）。 */
  deserialize: (raw: string) => T | null;
  /** 変わるたびに、その時点のdeserializeで読み直す（省略時はマウントの1回だけ）。deserializeが実行時に届く一覧
   * （軸カタログ等）で復元する値を決めるとき、届いたことを渡す。 */
  reloadKey?: unknown;
}

type StoredStateSetter<T> = (value: T | ((prev: T) => T)) => void;

function restore<T>(raw: string | null, deserialize: (raw: string) => T | null): T | null {
  if (raw == null) return null;
  try {
    return deserialize(raw);
  } catch {
    return null;
  }
}

// localStorageへ保存し、読み込み直しても復元するuseState。
//
// 保存はeffectではなくsetterのたびに書く——effectで保存すると、StrictModeの再マウントで「復元前の初期値の保存」が
// 割り込み、保存済みの設定を既定値で上書きする。
export function useStoredState<T>(
  key: string,
  defaultValue: T,
  { serialize, deserialize, reloadKey }: UseStoredStateOptions<T>,
): [T, StoredStateSetter<T>] {
  const [value, setValue] = useState(defaultValue);
  // serializeは描画ごとに別の関数で届くが、setterの参照は安定させたい（ほかの依存に使われる）。
  const serializeRef = useRef(serialize);
  useIsomorphicLayoutEffect(() => {
    serializeRef.current = serialize;
  });

  useIsomorphicLayoutEffect(() => {
    setValue(restore(readStoredValue(key), deserialize) ?? defaultValue);
    // defaultValueは依存に入れない（呼び出し側が描画ごとに新しいリテラルを渡すため、入れると読み直しが止まらない）。
  }, [key, reloadKey]);

  const setStoredValue = useCallback<StoredStateSetter<T>>(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (prev: T) => T)(prev) : next;
        try {
          writeStoredValue(key, serializeRef.current(resolved));
        } catch {}
        return resolved;
      });
    },
    [key],
  );

  return [value, setStoredValue];
}

// JSONで保存するuseState。
export function useStoredJsonState<T>(key: string, defaultValue: T): [T, StoredStateSetter<T>] {
  return useStoredState<T>(key, defaultValue, {
    serialize: JSON.stringify,
    deserialize: (raw) => JSON.parse(raw) as T,
  });
}

// 真偽値1つを保存するuseState。**保存値の型まで確かめる**（JSONのままだと`"3"`や`"null"`が流れ込む）。
export function useStoredBooleanState(key: string, defaultValue: boolean): [boolean, StoredStateSetter<boolean>] {
  return useStoredState<boolean>(key, defaultValue, {
    serialize: JSON.stringify,
    deserialize: (raw) => {
      const parsed: unknown = JSON.parse(raw);
      return typeof parsed === "boolean" ? parsed : null;
    },
  });
}
