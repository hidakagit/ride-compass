"use client";

import { useEffect, useState } from "react";
import { getMaterialValues } from "@/services/materialCatalogApi";

interface MaterialValuesState {
  materialId: string | null;
  values: readonly string[];
}

/** 材料の実データ値一覧（改善計画T340）。軸スタジオ（AxisComposer.tsx）が
 * highway/surface/smoothnessのようなオープンエンドな多値材料の値入力欄を、
 * テキスト自由入力から選択式へ切り替えるために使う。
 *
 * `materialId`がnull、または動的値一覧に対応していない材料（bicycle_infra等）・
 * DB未接続・DB障害・取得中はいずれも空配列を返す——呼び出し側は空配列を
 * 「動的値一覧が使えない」の合図として自由テキスト入力へフォールバックする
 * （useMaterialCatalogと違い静的フォールバック一覧を持たない。値の一覧は材料ごとに
 * 異なる実データそのものであり、コード側で妥当なフォールバック値を用意できないため）。
 */
export function useMaterialValues(materialId: string | null): readonly string[] {
  const [state, setState] = useState<MaterialValuesState>({ materialId, values: [] });

  // materialIdが変わった直後（このレンダーの間）は、前の材料の値一覧を一瞬でも
  // 引きずらないようレンダー中に同期して読み替える（Reactが推奨する「propが変わったら
  // stateをリセットする」パターン。effect側でsetStateすると`react-hooks/set-state-in-effect`
  // に抵触するため、リセット自体はeffectを使わずここで行う）。
  const values = state.materialId === materialId ? state.values : [];

  useEffect(() => {
    if (materialId === null) {
      return;
    }
    let cancelled = false;
    getMaterialValues(materialId)
      .then((response) => {
        if (!cancelled) {
          setState({ materialId, values: response.values });
        }
      })
      .catch(() => {
        // 取得失敗（未知の材料id=404、ネットワーク障害等）は空配列のまま
        // （fetchJsonが既にdebugLogへ記録済み）。
      });
    return () => {
      cancelled = true;
    };
  }, [materialId]);

  return values;
}
