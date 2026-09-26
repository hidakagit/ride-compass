"use client";

// 材料の値が実データでどの範囲に散らばっているかの取得（軸スタジオ）。
// 折れ点をどこへ置くかは、その材料が実際に取る値を知らないと決められない。
// カタログの`reference_points`はコードに書いた代表値で、実データの分布ではない。

import { useQuery } from "@tanstack/react-query";

import { fetchMaterialDistribution, type MaterialDistribution } from "@/features/admin/adminApi";
import { getQueryClient } from "@/lib/queryClient";

interface MaterialDistributionResult {
  distribution: MaterialDistribution | null;
  loading: boolean;
}

/** 値域は編集の補助情報のため、取得できなければ黙って出さない（他の欄の編集を妨げない）。失敗そのものは
 *  クライアントの骨格がdebugLogへ残す。取得できなかったこと（null）も値として覚える——覚えないと、値を
 *  持たない材料へマウントのたびに同じ失敗リクエストを投げ続ける。 */
async function fetchOrNull(materialId: string): Promise<MaterialDistribution | null> {
  try {
    return await fetchMaterialDistribution(materialId);
  } catch {
    return null;
  }
}

/** 同じ材料を複数の行が選んでも、開いている間に取りに行くのは1回（材料の分布は編集の間に変わらない）。 */
export function useMaterialDistribution(materialId: string | undefined): MaterialDistributionResult {
  const { data, isLoading } = useQuery(
    {
      queryKey: ["material-distribution", materialId],
      queryFn: () => fetchOrNull(materialId ?? ""),
      enabled: Boolean(materialId),
      staleTime: Infinity,
      gcTime: Infinity,
    },
    getQueryClient(),
  );
  return { distribution: data ?? null, loading: isLoading };
}
