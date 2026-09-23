"use client";

import { useCallback, useEffect, useState } from "react";

// 「今」を進める刻み。出発時刻として選べる値そのものが5分刻みのため
// （RideConditionBar/departureTimeline.ts）、これより細かく進めてもどの気象レイヤーが選ぶ
// フレームも変わらないまま、時刻をキーに持つ取得（useDedicatedWayValues）だけが無効化される。
const NOW_STEP_MS = 5 * 60 * 1000;
// 刻みの境界を跨いだかを見に行く間隔。刻みそのものより短くないと境界を跨ぎ越す。
const NOW_POLL_INTERVAL_MS = 30 * 1000;

function steppedNow(): Date {
  return new Date(Math.floor(Date.now() / NOW_STEP_MS) * NOW_STEP_MS);
}

interface DepartureTime {
  /** 出発時刻。気象レイヤーの表示時刻・専用配信軸の`at`・生成リクエストの`start_time`が同じ値を読む。 */
  at: Date;
  /** 刻みへ丸めた現在時刻。 */
  now: Date;
  /** 利用者が選んだ時刻か。falseの間の`at`は「今」に張り付いて進むため、利用者が決めた条件
   * としては扱えない（`features/route/generationRequest.ts`の比較キー参照）。 */
  pinned: boolean;
  setAt: (time: Date) => void;
  /** 「今」への追従へ戻す。 */
  followNow: () => void;
}

/** 出発時刻（走行条件の1つ）。選ぶまでは「今」へ追従する——止まったままだと、実況由来の
 * 気象フレーム列は先頭が前進するのに時刻だけが取り残され、降水・雷等が範囲外で黙って消える。
 * 選んだ時刻は勝手に動かさない（利用者が意図して決めた値）。 */
export function useDepartureTime(): DepartureTime {
  const [now, setNow] = useState(steppedNow);
  const [pinnedAt, setPinnedAt] = useState<Date | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow((previous) => {
        const next = steppedNow();
        return next.getTime() === previous.getTime() ? previous : next;
      });
    }, NOW_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const followNow = useCallback(() => {
    setNow(steppedNow());
    setPinnedAt(null);
  }, []);

  return { at: pinnedAt ?? now, now, pinned: pinnedAt !== null, setAt: setPinnedAt, followNow };
}
