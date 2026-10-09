"use client";

import { useEffect, useState } from "react";

/** いま見えている範囲の、fixed の要素の基準（layout viewport）の上端からの位置と高さ。 */
export interface VisibleArea {
  top: number;
  height: number;
}

/**
 * いま見えている範囲（visual viewport）を、`active`の間だけ追う。スマホのキーボードが出ると、ブラウザは fixed の基準を縮めずに
 * 見える範囲だけを縮めて送るので、fixed で画面の下まで置いたものはキーボードの裏に入る。見える範囲に収めたい fixed の要素は、
 * この上端と高さで置く。読めない環境（`visualViewport`の無いブラウザ）と`active`でない間は null。
 */
export function useVisualViewport(active: boolean): VisibleArea | null {
  const [area, setArea] = useState<VisibleArea | null>(null);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!active || !viewport) return;
    const update = () => setArea({ top: viewport.offsetTop, height: viewport.height });
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
    };
  }, [active]);

  return active ? area : null;
}
