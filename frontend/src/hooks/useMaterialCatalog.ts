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
        // 実バグ修正（デッドコード監査、2026-08-25）: 以前は`response.materials.length > 0`も
        // ガード条件に含めており、useAxisCatalog.tsで既に修正した同型のバグ（「まだ取得中/
        // 取得失敗」と「取得成功したが材料が0件」を同一視していた）を持っていた。後者でも
        // 静的フォールバック（AXIS_MATERIAL_OPTIONS、既存9材料）が残り続け、backend側の
        // material_catalog.pyが（運用上の一時的な状態等で）0件を返しても軸コンポーザーには
        // 常に9材料が出続けてしまう。取得成功時はmaterialsが空でもそのままsetMaterials
        // する（フェッチ未完了・失敗時のみAXIS_MATERIAL_OPTIONSに留まる、という区別に一本化）。
        if (!cancelled) {
          setMaterials(
            response.materials.map((m) => ({
              id: m.material_id,
              label: m.label,
              dtype: m.dtype,
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
