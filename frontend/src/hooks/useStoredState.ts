"use client";

import { useCallback, useRef, useState } from "react";
import { useIsomorphicLayoutEffect } from "./useIsomorphicLayoutEffect";

interface UseStoredStateOptions<T> {
  /** localStorageへ書き込む文字列への変換（JSON化するかは呼び出し側が選ぶ。
   * 既存の生文字列保存キー（route-style-mode等）と形式互換を保つため）。 */
  serialize: (value: T) => string;
  /** 保存文字列からTへの変換。不正・旧形式の値はnullを返す（デフォルト値のまま扱われる）。 */
  deserialize: (raw: string) => T | null;
  /** false時、setterは状態更新のみを行い保存しない。呼び出し側がcommit（戻り値の3番目）で
   * 保存タイミングを明示的に制御したいケース向け（例: ドラッグ中は毎フレーム状態更新するが
   * 保存はドラッグ確定時のみ、という分離。既定はtrue＝setterのたびに保存）。 */
  autoSave?: boolean;
  /** 復元処理（localStorageの読み出し→deserialize→setValue）を再実行させたいタイミングを
   * 表す追加の依存値（省略時は初回マウント時の1回のみ復元、元の挙動）。値が変わるたびに、
   * その時点の最新のdeserializeクロージャで再度localStorageから読み直す。
   * 例: deserializeが実行時カタログ（axisCatalog.rampAxes等）を参照して復元対象キーを
   * 決めているとき、この値にaxisCatalog.loadedを渡すと、マウント直後（未フェッチ、静的
   * フォールバック集合で復元）→フェッチ完了後（実行時集合で再復元）の2段階復元になる
   * （page.tsx: layerVisibility参照）。 */
  reloadKey?: unknown;
}

// localStorageへ保存し、リロード後も復元するuseState（改善計画T47 R-6:
// page.tsxに散在していたlocalStorage読み書きの手書きペアを1箇所へ集約）。
//
// 復元はuseStateの初期化子ではなくマウント後のlayout effectで行う（SSR時に生成される
// HTMLとハイドレーション結果がずれるため。ちらつき防止のためlayoutEffectを使う理由は
// useIsomorphicLayoutEffect参照）。読み書きとも失敗（プライベートブラウジング等で
// localStorageが使えない環境）はデフォルト値へのフォールバックとして握りつぶす。
//
// 保存は「エフェクトで自動保存」ではなく、setter呼び出しのたびに（autoSave=falseでなければ）
// 即書き込む。エフェクトでの保存だと、開発時StrictModeの再マウントで「復元前の初期値の保存」が
// 復元読み出しへ割り込み、保存済み設定を既定値で上書きする実害が過去にあったため（T32）。
export function useStoredState<T>(
  key: string,
  defaultValue: T,
  { serialize, deserialize, autoSave = true, reloadKey }: UseStoredStateOptions<T>
): [T, (value: T | ((prev: T) => T)) => void, (value: T) => void] {
  const [value, setValue] = useState(defaultValue);
  // serializeは呼び出し側がインライン関数で渡すため参照が毎レンダー変わりうるが、
  // commit/setStoredValueの参照自体は安定させたい（他のuseCallbackの依存に使われるため）。
  // refへの代入はレンダー中ではなくeffectで行う（レンダー中のref書き込みはeslintのreact-hooks/refsで禁止）。
  const serializeRef = useRef(serialize);
  useIsomorphicLayoutEffect(() => {
    serializeRef.current = serialize;
  });

  // deserializeは意図的にrefへ退避しない（reloadKeyが変わった際、その時点の最新の
  // deserializeクロージャを使って再復元したいため。reloadKey省略時はkeyが不変な限り
  // このeffectは初回のみ実行される、元の挙動のまま）。
  useIsomorphicLayoutEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw == null) return;
      const parsed = deserialize(raw);
      if (parsed != null) setValue(parsed);
    } catch {
      // 読み出し不可・壊れた値はデフォルトのまま
    }
  }, [key, reloadKey]);

  const commit = useCallback(
    (next: T) => {
      try {
        window.localStorage.setItem(key, serializeRef.current(next));
      } catch {
        // 保存不可でもこのセッション内の値は有効
      }
    },
    [key]
  );

  const setStoredValue = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (prev: T) => T)(prev) : next;
        if (autoSave) commit(resolved);
        return resolved;
      });
    },
    [autoSave, commit]
  );

  return [value, setStoredValue, commit];
}

// JSON直列化のuseStoredState（改善計画T270）。researchモード関連のstate（評価重み・
// route_preference等）をpage.tsx/admin/page.tsxの2ルート間で共有する際に、
// 呼び出し側でserialize/deserializeを毎回書かずに済むようにする薄いラッパー。
// 壊れた保存値はデフォルト値へフォールバックする（useStoredStateの既定動作）。
export function useStoredJsonState<T>(
  key: string,
  defaultValue: T
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
