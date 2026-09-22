"use client";

import { useState } from "react";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";

// スマホ幅かどうかの判定は**CSSが持つ**（`app/globals.css`の`--is-mobile`）。幅の分岐を
// 書けるのはメディアクエリだけで、ここに同じ数値を置くと写しになる——片方だけ動くと
// 「CSSはオーバーレイ表示なのにJSはデスクトップ判定」という形でずれる。
//
// SSR時はwindowが無いためfalse（デスクトップ扱い）で初期化し、マウント後に実際の値を
// 反映する。インラインstyleでは@mediaクエリを表現できないため、クラス名の出し分け等は
// JS側の判定が要る。
//
// 判定と初回反映はuseIsomorphicLayoutEffect（クライアントではuseLayoutEffect）で行う。
// 通常のuseEffectだとブラウザの初回ペイント後に非同期で実行されるため、モバイル幅で
// 開いた瞬間にデスクトップ相当のレイアウト（サイドバー全開のドロワー）が一瞬見えてから
// 折りたたまれる「ちらつき」が発生する。ペイント前に同期実行されるuseLayoutEffectを使うことで、
// 初回ペイントの時点で既に正しいisMobile値が反映された状態にする。
function readIsMobileFlag(): boolean {
  return window.getComputedStyle(document.documentElement).getPropertyValue("--is-mobile").trim() === "1";
}

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
