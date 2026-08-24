"use client";

import { useEffect, useState } from "react";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { AXIS_MATERIAL_OPTIONS } from "@/lib/axisMaterialsCatalog";
import { getMaterialCatalog } from "@/services/materialCatalogApi";

/** 材料カタログ（改善計画T277）。マウント時に一度`GET /api/material-catalog`を取得し、
 * backend/app/domain/material_catalog.pyへ追加された材料をコード変更・再デプロイなしに
 * 軸スタジオへ反映する。取得完了までとエラー時は静的フォールバック
 * （lib/axisMaterialsCatalog.ts、本フックが実装される前の軸スタジオが使っていたのと
 * 同じ9材料）を返すため、呼び出し側は常に何かしらの一覧を受け取れる。 */
export function useMaterialCatalog(): readonly AxisMaterialOption[] {
  const [materials, setMaterials] = useState<readonly AxisMaterialOption[]>(AXIS_MATERIAL_OPTIONS);

  useEffect(() => {
    let cancelled = false;
    getMaterialCatalog()
      .then((response) => {
        if (!cancelled && response.materials.length > 0) {
          setMaterials(
            response.materials.map((m) => ({
              id: m.material_id,
              label: m.label,
              boolean: m.dtype === "boolean",
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
