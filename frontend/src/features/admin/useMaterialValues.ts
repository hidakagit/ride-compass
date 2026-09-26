"use client";

import { useQuery } from "@tanstack/react-query";
import type { MaterialValueEntry } from "@/types/route";
import { getMaterialValues } from "@/features/admin/adminApi";
import { getQueryClient } from "@/lib/queryClient";

const NO_VALUES: readonly MaterialValueEntry[] = [];

/** 材料の実データ値一覧。軸スタジオ（AxisComposer.tsx）が
 * highway/surface/smoothnessのようなオープンエンドな多値材料の値入力欄を、
 * テキスト自由入力から選択式へ切り替えるために使う。各値の日本語ラベル(label)は
 * backend/app/domain/material_catalog.py: MaterialSpec.value_labelsが単一ソース
 * （地図の絞り込みUIのグルーピングとは独立）。
 *
 * `materialId`がnull、または動的値一覧に対応していない材料・取得中は
 * 空配列を返す——呼び出し側は空配列を「動的値一覧が使えない」の合図として自由テキスト
 * 入力へフォールバックする（材料カタログと違い静的な一覧を持たない。
 * 値の一覧は材料ごとに異なる実データそのものであり、コード側で妥当なフォールバック値を
 * 用意できないため）。材料を切り替えた直後は、前の材料の値一覧を返さない。
 *
 * 候補を**出せなかった**（DB障害・タイムアウト・通信失敗。未知の材料idの404を含む）ことは`unavailable`で
 * 区別して返す。「候補が無い」（取得できて0件）と同じ空配列へ倒すと、DBのタイムアウトが「この材料には値が
 * 無い」として静かに表示される——フォールバックの動きは同じでも、利用者に見せる理由が違う。
 */
export function useMaterialValues(materialId: string | null): {
  values: readonly MaterialValueEntry[];
  unavailable: boolean;
} {
  const { data, isError } = useQuery(
    {
      queryKey: ["material-values", materialId],
      queryFn: () => getMaterialValues(materialId ?? ""),
      enabled: materialId !== null,
    },
    getQueryClient(),
  );
  if (materialId === null) return { values: NO_VALUES, unavailable: false };
  if (isError) return { values: NO_VALUES, unavailable: true };
  return { values: data?.values ?? NO_VALUES, unavailable: data?.available === false };
}
