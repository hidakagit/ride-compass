"use client";

import { useEffect, useLayoutEffect } from "react";

// useLayoutEffectはSSR時に「サーバーでは実行できない」という警告が出るため、サーバー側では
// 実質同じ意味を持つuseEffectにフォールバックする定番のエイリアス。クライアントでは
// useLayoutEffectとして動作し、ブラウザが最初のペイントを行う前に同期的にstateを確定できる
// （初期表示時のちらつき防止に使う。useEffectはペイント後に非同期実行されるため、
// viewport幅に応じた表示切り替えのような「初回描画で正しい見た目にしたい」用途には向かない）。
export const useIsomorphicLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;
