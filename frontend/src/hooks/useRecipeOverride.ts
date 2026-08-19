"use client";

import { useState } from "react";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

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
export function useRecipeOverride<T>(defaultRecipe: T, debounceMs: number): RecipeOverride<T> {
  const [overrideEnabled, setOverrideEnabled] = useState(false);
  const [recipe, setRecipe] = useState<T>(defaultRecipe);
  const debouncedRecipe = useDebouncedValue(recipe, debounceMs);

  return { overrideEnabled, setOverrideEnabled, recipe, setRecipe, debouncedRecipe };
}
