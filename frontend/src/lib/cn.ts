import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// components/ui/配下のTailwindクラス合成用ヘルパー。clsxで条件付き
// className・配列・falsy値をまとめ、tailwind-mergeで「同じCSSプロパティを指す
// クラスの後勝ち」を正しく解決する(例: デフォルトの"p-2"を呼び出し側の"p-4"で
// 上書きする際、単純な文字列結合だとTailwindの生成順序次第でどちらが勝つか不定に
// なるが、tailwind-mergeは意味的に解決する)。shadcn/ui等で標準的なパターン。
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
