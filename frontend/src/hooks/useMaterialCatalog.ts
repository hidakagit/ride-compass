"use client";

import { useEffect, useState } from "react";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { getMaterialCatalog } from "@/services/materialCatalogApi";

// useAxisCatalog.tsと同じ同時フェッチ排除。複数の箇所から同時にマウントされても
// `GET /api/material-catalog`は1回で済む。
let inFlightMaterialCatalogFetch: ReturnType<typeof getMaterialCatalog> | null = null;

function fetchMaterialCatalogDeduped(): ReturnType<typeof getMaterialCatalog> {
  if (inFlightMaterialCatalogFetch) return inFlightMaterialCatalogFetch;
  const request = getMaterialCatalog().finally(() => {
    if (inFlightMaterialCatalogFetch === request) inFlightMaterialCatalogFetch = null;
  });
  inFlightMaterialCatalogFetch = request;
  return request;
}

export interface MaterialCatalogState {
  materials: readonly AxisMaterialOption[];
  /** 取得が終わったか。成功・失敗のどちらでも真になる。**空と読み込み中を混同しない**
   *  ——静的な写しで埋めると、backendへ材料を足しても古い一覧が出続ける。 */
  loaded: boolean;
}

/** 材料カタログ。マウント時に一度`GET /api/material-catalog`を取得する。 */
export function useMaterialCatalog(): MaterialCatalogState {
  const [state, setState] = useState<MaterialCatalogState>({ materials: [], loaded: false });

  useEffect(() => {
    let cancelled = false;
    fetchMaterialCatalogDeduped()
      .then((response) => {
        if (!cancelled) {
          setState({
            loaded: true,
            materials:
              response.materials.map((m) => ({
                id: m.material_id,
                label: m.label,
                name: m.name,
                description: m.description,
                dtype: m.dtype,
                unit: m.unit,
                referencePoints: m.reference_points,
              })),
          });
        }
      })
      .catch(() => {
        // fetchJsonが既にdebugLogへ記録済み。
        if (!cancelled) setState({ materials: [], loaded: true });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
