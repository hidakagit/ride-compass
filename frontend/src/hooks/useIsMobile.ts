"use client";

import { useState } from "react";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";

// スマホ幅（サイドバーをオーバーレイ表示に切り替える等の判定に使う）。
// 対象は概ね360-430px程度のスマートフォン縦持ち画面だが、多少余裕を持たせている。
// globals.cssの`@media (max-width: ...)`もこの値と一致させる必要がある
// （frontend/src/hooks/useIsMobile.test.tsで一致を自動検証している）。
export const MOBILE_BREAKPOINT_PX = 640;
const MOBILE_MEDIA_QUERY = `(max-width: ${MOBILE_BREAKPOINT_PX}px)`;

// SSR時はwindowが無いためfalse（デスクトップ扱い）で初期化し、マウント後に実際の幅を反映する。
// インラインstyleでは@mediaクエリを表現できないため、JS側で幅を判定してクラス名の出し分け等に使う。
//
// 判定と初回反映はuseIsomorphicLayoutEffect（クライアントではuseLayoutEffect）で行う。
// 通常のuseEffectだとブラウザの初回ペイント後に非同期で実行されるため、モバイル幅で
// 開いた瞬間にデスクトップ相当のレイアウト（サイドバー全開のドロワー）が一瞬見えてから
// 折りたたまれる「ちらつき」が発生する。ペイント前に同期実行されるuseLayoutEffectを使うことで、
// 初回ペイントの時点で既に正しいisMobile値が反映された状態にする。
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useIsomorphicLayoutEffect(() => {
    const mql = window.matchMedia(MOBILE_MEDIA_QUERY);
    const handleChange = (e: MediaQueryListEvent | MediaQueryList) => setIsMobile(e.matches);
    handleChange(mql);
    mql.addEventListener("change", handleChange);
    return () => mql.removeEventListener("change", handleChange);
  }, []);

  return isMobile;
}
