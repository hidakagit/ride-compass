"use client";

import { useState } from "react";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";

function readIsMobileFlag(): boolean {
  return window.getComputedStyle(document.documentElement).getPropertyValue("--is-mobile").trim() === "1";
}

// インラインstyleでは@mediaクエリを表現できないため、クラス名の出し分け等はJS側の判定が要る。
// 判定はペイント前に反映する——useEffectだと、モバイル幅で開いた瞬間にデスクトップのレイアウト
// （サイドバー全開のドロワー）が一瞬見えてから折りたたまれる。
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useIsomorphicLayoutEffect(() => {
    const update = () => setIsMobile(readIsMobileFlag());
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return isMobile;
}
