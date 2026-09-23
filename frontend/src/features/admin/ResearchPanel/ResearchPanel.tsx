"use client";

import { useResearchEnabled } from "@/hooks/useResearchMode";

// 研究モードON/OFFの操作導線は一般公開ページ（frontend/src/app/page.tsx）の
// ヘッダーメニュー（HeaderMenu.tsx）に一本化してある——同じフラグを2箇所で操作できる
// 状態（更新の取りこぼし・どちらが正か分かりにくい）を避けるため、ここではチェックボックス
// を置かず現在値の読み取り専用表示のみにする。フラグ自体（researchMode.ts）は変更せず、
// 一般公開ページの実験スロット比較（ComparisonPanel）の表示条件としてこの値を
// 引き続き参照する（page.tsx参照）。
export default function ResearchPanel() {
  const enabled = useResearchEnabled();

  return (
    <p className="text-[length:var(--font-size-md)]">
      研究モード: <strong>{enabled ? "ON" : "OFF"}</strong>
      （一般公開ページのヘッダーメニューから切り替えられます）
    </p>
  );
}
