"use client";

import { useEffect, useState } from "react";
import type { MaterialValueEntry } from "@/types/route";
import { getMaterialValues } from "@/services/materialCatalogApi";

interface MaterialValuesState {
  materialId: string | null;
  values: readonly MaterialValueEntry[];
  /** 候補を**出せなかった**（DB未接続・DB障害・タイムアウト・通信失敗）。
   * 「候補が無い」（取得できて0件）と区別する——同じ空配列へ倒すと、DBのタイムアウトが
   * 「この材料には値が無い」として静かに表示される。 */
  unavailable: boolean;
}

/** 材料の実データ値一覧。軸スタジオ（AxisComposer.tsx）が
 * highway/surface/smoothnessのようなオープンエンドな多値材料の値入力欄を、
 * テキスト自由入力から選択式へ切り替えるために使う。各値の日本語ラベル(label)は
 * backend/app/domain/material_catalog.py: MaterialSpec.value_labelsが単一ソース
 * （地図の絞り込みUIのグルーピングとは独立）。
 *
 * `materialId`がnull、または動的値一覧に対応していない材料（bicycle_infra等）・取得中は
 * 空配列を返す——呼び出し側は空配列を「動的値一覧が使えない」の合図として自由テキスト
 * 入力へフォールバックする（useMaterialCatalogと違い静的フォールバック一覧を持たない。
 * 値の一覧は材料ごとに異なる実データそのものであり、コード側で妥当なフォールバック値を
 * 用意できないため）。
 *
 * DB未接続・DB障害・通信失敗は`unavailable`で区別して返す。フォールバックの動きは同じでも、
 * **利用者に見せる理由が違う**（候補が無いのか、出せなかったのか）。
 */
export function useMaterialValues(materialId: string | null): {
  values: readonly MaterialValueEntry[];
  unavailable: boolean;
} {
  const [state, setState] = useState<MaterialValuesState>({ materialId, values: [], unavailable: false });

  // materialIdが変わった直後（このレンダーの間）は、前の材料の値一覧を一瞬でも
  // 引きずらないようレンダー中に同期して読み替える（Reactが推奨する「propが変わったら
  // stateをリセットする」パターン。effect側でsetStateすると`react-hooks/set-state-in-effect`
  // に抵触するため、リセット自体はeffectを使わずここで行う）。
  const current = state.materialId === materialId ? state : { values: [], unavailable: false };

  useEffect(() => {
    if (materialId === null) {
      return;
    }
    let cancelled = false;
    getMaterialValues(materialId)
      .then((response) => {
        if (!cancelled) {
          setState({ materialId, values: response.values, unavailable: response.available === false });
        }
      })
      .catch(() => {
        // 取得失敗（未知の材料id=404、ネットワーク障害等）。fetchJsonが既にdebugLogへ
        // 記録済みなので、ここでは画面が理由を出せるよう印だけ残す。
        if (!cancelled) setState({ materialId, values: [], unavailable: true });
      });
    return () => {
      cancelled = true;
    };
  }, [materialId]);

  return { values: current.values, unavailable: current.unavailable };
}
