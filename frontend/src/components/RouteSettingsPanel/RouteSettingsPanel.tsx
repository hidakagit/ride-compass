"use client";

import { useEffect, useState } from "react";
import LayerChip from "@/components/Map/LayerChip";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { FieldLabel, withAutoEnable } from "@/components/Map/recipeControls";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { MapLayerId, MapLayerVisibility } from "@/components/Map/mapLayers";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { HardFilterOverride, RoutePreferenceWeights } from "@/types/route";
import styles from "./RouteSettingsPanel.module.css";

// 一般ユーザー向けルート設定画面（改善計画T267、目論見書4章「①一般ユーザ向け
// ルーティング設定」）。研究モード（WeightPanel）とは別の導線で、常に表示される
// メインの操作面に置く。0次(除外)→軸選択+重み→重み配分の可視化、という並びは
// 提示済みのモックアップをそのまま実装したもの。
//
// プリセット（「バランス」「自転車専用道を優先」等のボタン）は撤去した（2026-08-27
// ユーザー判断: 重み配分の根拠が不明瞭なため）。既存7軸を名指しした固定の重み値
// （「叩き台」段階のまま実走検証を経ていなかった）だったが、後日きちんと設計した
// プロファイル機能として再実装する想定。復元する場合はgit履歴（本コミット直前）参照。
//
// 改善計画T306: 以前は軸を観測/推定/動的の3カテゴリへ見出し付きで分けて表示していた
// （T267の意図的な設計判断）。しかし改善計画T305で軸スタジオのGUIが常にcategory="推定"
// 固定で軸を作るようになった結果、「観測/動的グループに入るのはコード内蔵の既定軸だけ」
// というハードコードされた非対称性が生まれた。この非対称性を無くすため、ルート設定画面の
// 表示からカテゴリによるグルーピングを撤去し、公開済みの軸を（内部的な観測/推定/動的の
// 分類に関わらず）フラットに1本のリストとして表示する。軸の`category`データ自体は
// backend側にそのまま残す（他の用途・将来のプロファイル機能のために消さない）。
//
// 軸の一覧・既定重みはuseAxisCatalog（改善計画T269）経由でGET /api/axis-catalogから
// 取得する（is_published=Trueのみ）。軸スタジオ（T270）がDBへ追加した軸も、コード変更・
// 再デプロイなしにここへ現れる（取得完了まで・失敗時は既存7軸の静的フォールバックを使う）。

// backend/app/domain/evaluation.py: DEFAULT_HARD_FILTERSと同じ3種（改善計画T266）。
const HARD_FILTER_CHIPS: { key: string; label: string }[] = [
  { key: "no_bicycle", label: "自転車通行禁止" },
  { key: "motorway", label: "高速道路" },
  { key: "trunk", label: "幹線道路(trunk)" },
];

export const DEFAULT_HARD_FILTERS: HardFilterOverride = { no_bicycle: true, motorway: true, trunk: true };

// 重み配分バーの軸ごとの色分け（改善計画T267のモックアップと同じ配色を初期7色として流用）。
// 改善計画T320: 以前はCSS側でdata-axis属性値（axis_id文字列）ごとにセレクタを書いており、
// 軸スタジオで新規公開した軸は対応するセレクタが無いため無色（透明な帯）になっていた
// （色自体に意味は持たせない識別用のため、固定パレットで足りるという前提自体は変えず、
// axis_idではなく表示順indexで引く方式へ変更し、軸の増減にコード変更無しで追従させる）。
const STACK_BAR_COLORS = ["#7f77dd", "#1d9e75", "#d85a30", "#d4537e", "#378add", "#ef9f27", "#639922"];

function stackBarColorForIndex(index: number): string {
  return STACK_BAR_COLORS[index % STACK_BAR_COLORS.length];
}

function totalWeight(weights: RoutePreferenceWeights): number {
  return Object.values(weights).reduce((sum, w) => sum + (w > 0 ? w : 0), 0);
}

interface RouteSettingsPanelProps {
  hardFilters: HardFilterOverride;
  onHardFiltersChange: (next: HardFilterOverride) => void;
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (next: RoutePreferenceWeights) => void;
  /** route_preference上書き（研究モードのWeightPanelと共有する同じ状態、page.tsx参照）の
   * 有効フラグ。既定値のまま操作しなければ無効のままでよく（DEFAULT_ROUTE_PREFERENCE＝
   * backend YAML既定値のため挙動は変わらない）、値を変えると自動でONになる
   * （withAutoEnable、WeightPanel.tsxと同じパターン）。一般ユーザーはこのフラグの存在自体を
   * 意識しない（トグルUIをこのパネルには出さない）。 */
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  /** 改善計画T418: 軸ごとの「この条件で地図を色分け」トグル用。地図レイヤーの表示状態
   * （page.tsx: layerVisibility）をそのまま渡す。地図UIの評価軸チップを撤去したのに
   * 伴い、軸選択・重み設定と同じこの行から地図色分けを起動できるようにした
   * （docs/tasks/T418.md「やること」2.）。専用の表示レイヤーを持つ軸（kind="ramp"・
   * wind）だけがトグルを持ち、持たない軸（勾配等）は非対応の案内のみ出す。 */
  layerVisibility: MapLayerVisibility;
  onLayerToggle: (id: MapLayerId, on: boolean) => void;
  /** ルートが確定済みか（page.tsx: hasDetail）。改善計画T414の状態機械どおり、風
   * （windAxis）はルート確定後は視界内の全道路への一律色分けという役割を終了し、
   * 「生成したルートの色分け」の「風」モードへ案内する（T400.md「2.」節。T418で
   * この案内自体を地図上チップからルート設定パネルへ移設した）。風以外の軸
   * （car_stress等）は動的パラメータを持たないためルート確定後も一律色分けを続けられ、
   * この対象外のまま変更していない。 */
  hasDetail: boolean;
}

export default function RouteSettingsPanel({
  hardFilters,
  onHardFiltersChange,
  routePreference,
  onRoutePreferenceChange,
  overrideEnabled,
  onOverrideEnabledChange,
  layerVisibility,
  onLayerToggle,
  hasDetail,
}: RouteSettingsPanelProps) {
  const catalog = useAxisCatalog();
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

  // 改善計画T418: 軸id→地図表示レイヤーIDの解決。専用の表示レイヤーを持つ軸
  // （kind="ramp"、catalog.secondaryAxesのlayerId）はそのままレイヤーIDを返す。
  // 風（wind）はcatalog.secondaryAxesには現れない特殊軸だが、除外理由は
  // `show_map_icon=false`のみ（category自体は他の軸と同じ"推定"——旧コメントは
  // category="動的"のためと誤って説明していたが、2026-08-30にDBスナップショット
  // [backend/fixtures/axis_definitions_snapshot.json]で確認し訂正した）。
  // way_id→wind_penalty配信層「windAxis」という専用レイヤーを持つためaxisIdで直接
  // 判定する。どちらにも該当しない軸（勾配等、kind="none"）はundefined
  // （地図表示非対応、docs/tasks/T400.md「7. kind=noneが残る範囲」節参照）。
  function mapColorLayerIdFor(axisId: string): MapLayerId | undefined {
    if (axisId === "wind") return "windAxis";
    return catalog.secondaryAxes.find((a) => a.axisId === axisId)?.layerId;
  }

  // 改善計画T418: 軸1件ぶんの「地図で色分け」トグル。専用レイヤーが無い軸・ルート確定後の
  // 風はどちらも押せない案内表示にする（上記hasDetailのコメント参照）。トグル自体は
  // 既存のramp軸描画ロジック（axisVisibility、MapView.tsx）・windAxis配信層
  // （useWindAxisPenalties）をそのまま流用し、layerVisibility[layerId]のON/OFFを
  // 切り替えるだけ——このコンポーネントは地図描画そのものには関与しない。
  function renderMapColorToggle(axis: PreferenceAxisDef) {
    const layerId = mapColorLayerIdFor(axis.axisId);
    if (!layerId) {
      return (
        <span className={styles.mapColorUnavailable} title="この軸はまだ地図表示用のデータ取得経路が用意されていません[ルート探索のコストには反映されます]">
          地図表示なし
        </span>
      );
    }
    if (layerId === "windAxis" && hasDetail) {
      return (
        <span className={styles.mapColorUnavailable} title='ルート確定後は「生成したルートの色分け」の「風」で確認できます'>
          地図表示なし
        </span>
      );
    }
    const on = layerVisibility[layerId] ?? false;
    return (
      <span className={styles.mapColorToggle}>
        <LayerChip
          label="色分け"
          on={on}
          ariaLabel={`${axis.label}で地図を色分け表示`}
          onClick={() => onLayerToggle(layerId, !on)}
        />
      </span>
    );
  }

  // カタログとroutePreferenceのキー集合を双方向に同期する（改善計画T269・T302）。
  // backendのroute_preference検証は「上書きするなら既知の全axis_idを明示する」方針
  // （キー完全一致、routers/routes.py: RoutePreferenceWeights._check_axis_keys）のため、
  // どちら向きのズレを放置してもルート生成が422になる（改善計画T269、将来のT270軸追加に
  // 備えた防御）。
  // - 新しい軸（軸スタジオがDBへ追加した軸）が現れた場合: その既定重みを補う。
  // - 軸が消えた場合（改善計画T302、公開軸のunpublish）: そのキーをroutePreferenceから
  //   削除する。これが無いと、unpublish直後に旧設定を保持したブラウザで次のルート生成が
  //   422で壊れる（docs/decisions/t221-axis-registry.md「Stage D拡張3」）。
  // どちらも値を変えずキーの追加/削除だけなのでoverrideEnabledは動かさない、
  // handlePreferenceChangeではなくonRoutePreferenceChangeを直接使う。
  useEffect(() => {
    const synced = syncRoutePreferenceKeys(routePreference, catalog.defaultWeights);
    if (synced) onRoutePreferenceChange(synced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.defaultWeights]);

  // チェックを外した軸の重みを覚えておき、再度チェックしたときに元へ戻す
  // （routePreference自体は常に0を含む「実際に送る値」のため、ここでしか保持できない）。
  const [lastWeights, setLastWeights] = useState<Record<string, number>>(() => ({
    ...catalog.defaultWeights,
  }));

  function handleToggle(axisId: string, checked: boolean) {
    const restored = checked ? lastWeights[axisId] || catalog.defaultWeights[axisId] || 0.1 : 0;
    handlePreferenceChange({ ...routePreference, [axisId]: restored });
  }

  function handleWeightChange(axisId: string, value: number) {
    setLastWeights((prev) => ({ ...prev, [axisId]: value }));
    handlePreferenceChange({ ...routePreference, [axisId]: value });
  }

  const total = totalWeight(routePreference);

  return (
    <div className="flex flex-col gap-3">
      <div className={styles.hardFilters}>
        <p className={styles.sectionLabel}>除外する道路</p>
        <div className={styles.chipRow}>
          {HARD_FILTER_CHIPS.map(({ key, label }) => (
            <LayerChip
              key={key}
              label={label}
              on={hardFilters[key] ?? true}
              ariaLabel={`${label}を除外`}
              onClick={() => onHardFiltersChange({ ...hardFilters, [key]: !(hardFilters[key] ?? true) })}
            />
          ))}
        </div>
      </div>

      <div className={styles.stackBarWrap}>
        <p className={styles.sectionLabel}>重み配分</p>
        <div className={styles.stackBar}>
          {catalog.axes.map(({ axisId, label }, index) => {
            const weight = routePreference[axisId] ?? 0;
            if (weight <= 0 || total <= 0) return null;
            const pct = (weight / total) * 100;
            return (
              <div
                key={axisId}
                className={styles.stackSegment}
                style={{ width: `${pct}%`, background: stackBarColorForIndex(index) }}
                title={`${label} ${Math.round(pct)}%`}
              />
            );
          })}
        </div>
      </div>

      <div className={styles.group}>
        {catalog.axes.map((axis) => {
          const weight = routePreference[axis.axisId] ?? 0;
          const checked = weight > 0;
          return (
            <div key={axis.axisId} className={styles.row}>
              {/* FieldLabelは説明ポップオーバーのボタンを内包するため、<label>で
                  checkboxと一緒に包まない（ネイティブlabelのクリック委譲でinfoボタン
                  押下時にもcheckboxがトグルされてしまう、WeightPanel.tsxのWeightInputと
                  同じ理由で兄弟要素として配置しaria-labelで関連付ける）。 */}
              <Checkbox
                checked={checked}
                onCheckedChange={(next) => handleToggle(axis.axisId, next)}
                aria-label={axis.label}
              />
              <span className={styles.rowLabel}>
                <FieldLabel label={axis.label} description={axis.description} />
              </span>
              <input
                type="range"
                min="0"
                max="0.6"
                step="0.01"
                value={weight}
                disabled={!checked}
                aria-label={`${axis.label}の重み`}
                onChange={(e) => handleWeightChange(axis.axisId, Number(e.target.value))}
                className={styles.slider}
              />
              <span className={styles.weightValue}>{weight.toFixed(2)}</span>
              {renderMapColorToggle(axis)}
            </div>
          );
        })}
      </div>

      <button
        type="button"
        className={styles.resetButton}
        onClick={() => {
          setLastWeights({ ...catalog.defaultWeights });
          handlePreferenceChange(catalog.defaultWeights);
          onHardFiltersChange(DEFAULT_HARD_FILTERS);
        }}
      >
        既定値に戻す
      </button>
    </div>
  );
}
