"use client";

import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useStoredJsonState } from "@/hooks/useStoredState";

export interface RecipeOverride<T> {
  overrideEnabled: boolean;
  setOverrideEnabled: (enabled: boolean) => void;
  recipe: T;
  setRecipe: (recipe: T) => void;
  /** 地図描画用のデバウン済みの値（連続入力のたびにMapLibreの再描画が走るのを防ぐ）。 */
  debouncedRecipe: T;
}

// レシピ（一次情報→二次情報の変換式、domain/recipe.py参照）の研究モード上書き状態
// （有効フラグ・値・地図反映用のデバウンス値）をまとめたフック。page.tsxでは車の圧迫感・
// 安全度・道路適正・自動車密度の4レシピが、この3点セット（useState×2 +
// useDebouncedValue×1）をそれぞれ独立にコピペしていた（改善計画T133、交通ストレス・
// 安全度の2軸から2軸増えて重複が倍化したため集約）。
//
// `storageKey`: overrideEnabled/recipeをlocalStorageへ永続化する（useStoredState経由）。
// 軸スタジオ（/admin、研究UIの移設先）とメインページ（page.tsx）が別ルートに分かれたため、
// Reactの状態を直接共有できない——同じキーでこのフックを呼べば、一方のページでの編集が
// localStorage経由でもう一方へ反映される（次回マウント時に読み出す、同一タブでの
// リアルタイム同期ではない点はlib/researchMode.ts等の既存パターンと同じ）。改善計画T270で
// 編集UIが全て/adminへ移設され、呼び出し元は例外なくstorageKeyを渡すようになったため
// （レビュー指摘の修正）、非永続のuseState分岐は廃止した。
export function useRecipeOverride<T>(defaultRecipe: T, debounceMs: number, storageKey: string): RecipeOverride<T> {
  const [overrideEnabled, setOverrideEnabled] = useStoredJsonState<boolean>(`${storageKey}:enabled`, false);
  const [recipe, setRecipe] = useStoredJsonState<T>(`${storageKey}:value`, defaultRecipe);
  const debouncedRecipe = useDebouncedValue(recipe, debounceMs);

  return { overrideEnabled, setOverrideEnabled, recipe, setRecipe, debouncedRecipe };
}
