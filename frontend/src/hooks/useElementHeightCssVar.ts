"use client";

import { useEffect, type RefObject } from "react";

/**
 * measureRefが指す要素の実測高さ(px)を、targetRefが指す祖先要素へCSSカスタムプロパティ
 * として反映し続ける（地図オーバーレイの▼ページ送り判定[MapOverlayControls.tsx:
 * usePagedOverflow]は、兄弟要素として重なる気象タイムラインパネル[page.tsx:
 * .bottomControlRow]の占有高さを直接は知らないため、これで補う）。
 *
 * 兄弟要素同士でDOMの高さを直接やり取りする手段が無いため、共通の祖先（page.tsxの
 * .mapPane）へinline styleでCSS変数を書き込み、そちらを参照する側（MapOverlayControls.
 * module.cssの.wrapper）のCSS計算へ反映させる（globals.cssの`--mobile-tabbar-height`と
 * 同じ「CSS変数で高さを共有する」パターン。あちらは固定値だが、こちらは
 * ResizeObserverで実測するため表示中のレイヤー数による高さの変化[.dynamicLayerSliders
 * のflex-wrap]にも追従する）。
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
