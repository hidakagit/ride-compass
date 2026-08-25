"use client";

import { useEffect, useState } from "react";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { PREFERENCE_AXES } from "@/lib/evaluationAxes";
import type { AxisCatalogEntry, RoutePreferenceWeights } from "@/types/route";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import axisCatalogStatic from "@/types/generated/axis-catalog.json";

// ビルド時静的生成物（既存7軸の既定重み、開発中のフォールバック用）。GET /api/axis-catalog
// （改善計画T269）はこれと同じ形の情報をDBの最新内容から動的に返す。
const STATIC_DEFAULT_WEIGHTS: RoutePreferenceWeights = axisCatalogStatic.preference_defaults;

export interface AxisCatalog {
  /** axisId・label・descriptionの一覧（フェッチ成功時はDB由来、失敗時は静的フォールバック）。 */
  axes: readonly PreferenceAxisDef[];
  /** axis_idから既定重みを引く。未知のaxis_idには0を返す。 */
  defaultWeights: RoutePreferenceWeights;
}

const FALLBACK_CATALOG: AxisCatalog = {
  axes: PREFERENCE_AXES,
  defaultWeights: STATIC_DEFAULT_WEIGHTS,
};

function buildCatalog(entries: readonly AxisCatalogEntry[]): AxisCatalog {
  const defaultWeights: RoutePreferenceWeights = {};
  const axes: PreferenceAxisDef[] = entries.map((entry) => {
    defaultWeights[entry.axis_id] = entry.default_weight;
    return { axisId: entry.axis_id, label: entry.label, description: entry.description };
  });
  return { axes, defaultWeights };
}

/** 軸カタログ（改善計画T269）。マウント時に一度`GET /api/axis-catalog`を取得し、
 * 軸スタジオ（T270）がDBへ追加した軸を反映する。取得完了までとエラー時は静的な
 * 既存7軸カタログ（フォールバック）を返すため、呼び出し側は常に何かしらの
 * 一覧を受け取れる（loading状態を個別に扱う必要がない）。
 *
 * 改善計画T306: 以前はaxis_idから観測/推定/動的カテゴリを引く`categoryOf`も持っていたが、
 * 唯一の消費者だったRouteSettingsPanelのカテゴリ別グルーピング表示を撤去したのに伴い削除。
 * backendのGET /api/axis-catalogレスポンス自体には引き続き`category`フィールドが含まれる
 * （他用途・将来のプロファイル機能のため）が、このフックはそれを消費しない。 */
export function useAxisCatalog(): AxisCatalog {
  const [catalog, setCatalog] = useState<AxisCatalog>(FALLBACK_CATALOG);

  useEffect(() => {
    let cancelled = false;
    getAxisCatalog()
      .then((response) => {
        if (!cancelled && response.axes.length > 0) {
          setCatalog(buildCatalog(response.axes));
        }
      })
      .catch(() => {
        // 取得失敗時はFALLBACK_CATALOGのまま（fetchJsonが既にdebugLogへ記録済み）。
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return catalog;
}
