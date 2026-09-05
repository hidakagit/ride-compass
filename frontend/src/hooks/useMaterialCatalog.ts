"use client";

import { useEffect, useState } from "react";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { AXIS_MATERIAL_OPTIONS } from "@/lib/axisMaterialsCatalog";
import { getMaterialCatalog } from "@/services/materialCatalogApi";

// useAxisCatalog.tsと同じ同時フェッチ排除パターン。useMaterialCatalogは現状
// <AxisComposer>単独からのみ呼ばれ同時マウントの実害は無いが、軸スタジオのUIが今後
// 複数箇所からこのフックを呼ぶ構成に変わっても同種の2重フェッチを再発させないための
// 予防的な統一（useAxisCatalog.tsとの一貫性）。
let inFlightMaterialCatalogFetch: ReturnType<typeof getMaterialCatalog> | null = null;

function fetchMaterialCatalogDeduped(): ReturnType<typeof getMaterialCatalog> {
  if (inFlightMaterialCatalogFetch) return inFlightMaterialCatalogFetch;
  const request = getMaterialCatalog().finally(() => {
    if (inFlightMaterialCatalogFetch === request) inFlightMaterialCatalogFetch = null;
  });
  inFlightMaterialCatalogFetch = request;
  return request;
}

/** 材料カタログ。マウント時に一度`GET /api/material-catalog`を取得し、backend/app/domain/
 * material_catalog.pyへ追加された材料をコード変更・再デプロイなしに軸スタジオへ反映する。
 * 取得完了までとエラー時は静的フォールバック（lib/axisMaterialsCatalog.ts）を返すため、
 * 呼び出し側は常に何かしらの一覧を受け取れる。 */
export function useMaterialCatalog(): readonly AxisMaterialOption[] {
  const [materials, setMaterials] = useState<readonly AxisMaterialOption[]>(AXIS_MATERIAL_OPTIONS);

  useEffect(() => {
    let cancelled = false;
    fetchMaterialCatalogDeduped()
      .then((response) => {
        // 取得成功時はmaterialsが空でもそのままsetMaterialsする（フェッチ未完了・失敗時のみ
        // AXIS_MATERIAL_OPTIONSに留まる、という区別に一本化）。取得成功した0件と
        // 未取得/失敗を同一視すると、backend側のmaterial_catalog.pyが（運用上の一時的な
        // 状態等で）0件を返しても軸コンポーザーには常に静的フォールバックの材料が
        // 出続けてしまう。
        if (!cancelled) {
          setMaterials(
            response.materials.map((m) => ({
              id: m.material_id,
              label: m.label,
              description: m.description,
              dtype: m.dtype,
              unit: m.unit,
              referencePoints: m.reference_points,
            })),
          );
        }
      })
      .catch(() => {
        // 取得失敗時はAXIS_MATERIAL_OPTIONSのまま(fetchJsonが既にdebugLogへ記録済み)。
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return materials;
}
