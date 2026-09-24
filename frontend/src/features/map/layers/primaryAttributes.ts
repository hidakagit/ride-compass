// 一次属性（生データ）のカタログ。
//
// 一次属性の正式名（label）は生成物`types/generated/primaryAttributes.ts`（backendの
// レジストリ宣言から書き出す）が単一ソース。
//
// 「2次軸→材料の一次属性一覧」（推定指標レイヤーON時の観測データレイヤー連動ON・
// 推定グループの展開UIに材料一覧を出す）は、backendのGET /api/axis-catalogが軸ごとに
// 解決して返すprimary_attribute_ids（SecondaryAxisSummary.primaryAttributeIds、
// secondaryAxes.ts参照）を呼び出し側が使う——GUI作成軸を含む全軸に対して同じ経路で
// 動く。

import { mapDisplay } from "@/types/generated/mapDisplay";
import type { MapLayerId } from "./mapLayers";
import { primaryAttributes as primaryAttributeCatalog } from "@/types/generated/primaryAttributes";

interface PrimaryAttribute {
  attrId: string;
  /** 正式名（サイドバー・研究タブで使う） */
  label: string;
}

/** 一次属性の一覧（正式名付き）。生成物`primaryAttributes.ts`（backendのレジストリ宣言から
 * 生成、DBを読まない）をそのまま反映する。 */
const PRIMARY_ATTRIBUTES: readonly PrimaryAttribute[] = primaryAttributeCatalog.map((attr) => ({
  attrId: attr.attr_id,
  label: attr.label,
}));

/** attr_id→正式名の辞書（区間インスペクタ・研究タブが引く）。 */
export const PRIMARY_ATTRIBUTE_LABELS: Record<string, string> = Object.fromEntries(
  PRIMARY_ATTRIBUTES.map((attr) => [attr.attrId, attr.label]),
);

/** 一次属性のうち、地図に出るもの。**源泉が決める**——`display_axes`を持つ（線・点）か
 * 面の幾何を持つものが出る。レイヤーの名前は属性idそのもので、対応表を持たない。
 *
 * 表を手で持つと「新しい属性を足したのに地図へ出ない／対応表への追加漏れ」が起き、
 * それを見張る検査が要る。源泉から導けば、そもそもずれる余地が無い。 */
const MAP_LAYER_ATTR_IDS: ReadonlySet<string> = new Set(mapDisplay.layers.map((layer) => layer.id));

/** 一次属性id列のうち、表示レイヤーを持つものだけをMapLayerIdの重複無し配列で返す
 * （推定指標レイヤーON時の観測データレイヤー連動ON用）。複数の一次属性が同じ表示
 * レイヤーへ集約される場合（1レイヤーが複数属性を表す場合）は1件にまとめる。引数は
 * attrId列（呼び出し側がSecondaryAxisSummary.primaryAttributeIds等、実行時カタログから
 * 既に持っている値）を受け取り、GUI作成軸を含む全軸に対して同じ関数で動く。 */
export function primaryAttributeIdsToLayerIds(attrIds: readonly string[]): readonly MapLayerId[] {
  const layerIds = attrIds.filter((attrId): attrId is MapLayerId => MAP_LAYER_ATTR_IDS.has(attrId));
  return Array.from(new Set(layerIds));
}
