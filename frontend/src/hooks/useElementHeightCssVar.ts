"use client";

import { useEffect, type RefObject } from "react";

/**
 * measureRefが指す要素の実測高さ(px)を、targetRefが指す祖先要素へCSSカスタムプロパティとして
 * 書き続ける。兄弟の要素どうしは互いの高さを知る手段が無いので、共通の祖先に置いた変数を読む側の
 * CSSが使う（例: スマホ幅の地図チップ列が、下に重なる時刻のスライダー列の高さぶん上へ逃げる）。
 * ResizeObserverで測るので、表示中のレイヤー数で折り返しが変わっても追従する。
 */
export function useElementHeightCssVar(
  measureRef: RefObject<HTMLElement | null>,
  targetRef: RefObject<HTMLElement | null>,
  varName: string,
): void {
  useEffect(() => {
    const measureEl = measureRef.current;
    const targetEl = targetRef.current;
    if (!measureEl || !targetEl) {
      return;
    }
    const applyHeight = (height: number) => {
      targetEl.style.setProperty(varName, `${height}px`);
    };
    applyHeight(measureEl.getBoundingClientRect().height);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        applyHeight(entry.contentRect.height);
      }
    });
    observer.observe(measureEl);
    return () => {
      observer.disconnect();
      targetEl.style.removeProperty(varName);
    };
  }, [measureRef, targetRef, varName]);
}
