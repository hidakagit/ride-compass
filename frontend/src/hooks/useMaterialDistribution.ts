"use client";

// 材料の値が実データでどの範囲に散らばっているかの取得（軸スタジオ）。
// 折れ点をどこへ置くかは、その材料が実際に取る値を知らないと決められない。
// カタログの`reference_points`はコードに書いた代表値で、実データの分布ではない。

import { useEffect, useState } from "react";

import { fetchMaterialDistribution, type MaterialDistribution } from "@/services/axisPreviewApi";

export interface MaterialDistributionResult {
  distribution: MaterialDistribution | null;
  loading: boolean;
}

/** 同じ材料を複数の行が選んでいても取得は1回で済むよう、結果をモジュール内で共有する。 */
const cache = new Map<string, MaterialDistribution>();

export function useMaterialDistribution(materialId: string | undefined): MaterialDistributionResult {
  const [result, setResult] = useState<MaterialDistributionResult>({ distribution: null, loading: false });

  useEffect(() => {
    let cancelled = false;
    // setStateの同期呼び出しを避けてマイクロタスク経由で実行する
    // （useDedicatedWayValuesと同じreact-hooks/set-state-in-effect対策）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!materialId) {
        setResult({ distribution: null, loading: false });
        return;
      }
      const cached = cache.get(materialId);
      if (cached) {
        setResult({ distribution: cached, loading: false });
        return;
      }
      setResult({ distribution: null, loading: true });
      try {
        const distribution = await fetchMaterialDistribution(materialId);
        cache.set(materialId, distribution);
        if (!cancelled) setResult({ distribution, loading: false });
      } catch {
        // 値域は編集の補助情報のため、取得できなければ黙って出さない（他の欄の
        // 編集を妨げない）。失敗そのものはaxisPreviewApiがdebugLogへ残す。
        if (!cancelled) setResult({ distribution: null, loading: false });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [materialId]);

  return result;
}
