"use client";

import { useEffect, useState } from "react";
import LayerChip from "@/components/Map/LayerChip";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { FieldLabel, withAutoEnable } from "@/components/Map/recipeControls";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { HardFilterOverride, RoutePreferenceWeights } from "@/types/route";
import styles from "./RouteSettingsPanel.module.css";

// 一般ユーザー向けルート設定画面（改善計画T267、目論見書4章「①一般ユーザ向け
// ルーティング設定」）。研究モード（WeightPanel）とは別の導線で、常に表示される
// メインの操作面に置く。0次(除外)→軸選択+重み→重み配分の可視化→プリセット、という
// 並びは提示済みのモックアップをそのまま実装したもの。
//
// 改善計画T306: 以前は軸を観測/推定/動的の3カテゴリへ見出し付きで分けて表示していた
// （T267の意図的な設計判断）。しかし改善計画T305で軸スタジオのGUIが常にcategory="推定"
// 固定で軸を作るようになった結果、「観測/動的グループに入るのはコード内蔵の既定軸だけ」
// というハードコードされた非対称性が生まれた。この非対称性を無くすため、ルート設定画面の
// 表示からカテゴリによるグルーピングを撤去し、公開済みの軸を（内部的な観測/推定/動的の
// 分類に関わらず）フラットに1本のリストとして表示する。軸の`category`データ自体は
// backend側にそのまま残す（他の用途・将来のプロファイル機能[下記]のために消さない）。
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

interface Preset {
  label: string;
  /** 部分指定可。未言及の軸は`catalog.defaultWeights`で補われる（applyPreset参照）。
   * カタログにまだ無い将来の軸を差し替え不要のまま安全に無視できる。 */
  weights: RoutePreferenceWeights;
}

// 既存7軸向けの重みは叩き台（目論見書8章「要判断事項」、実走検証を経て確定する）。
// バランスプリセットのみカタログの既定重みをそのまま使うため、コンポーネント内で組み立てる
// （PRESETS参照）。
const NON_DEFAULT_PRESETS: readonly Preset[] = [
  {
    label: "自転車専用道を優先",
    weights: {
      gradient: 0.1, surface_q: 0.12, stop_density: 0.22, night: 0.0,
      car_stress: 0.45, accident: 0.08, wind: 0.03,
    },
  },
  {
    label: "最短時間重視",
    weights: {
      gradient: 0.05, surface_q: 0.05, stop_density: 0.05, night: 0.0,
      car_stress: 0.05, accident: 0.0, wind: 0.1,
    },
  },
  {
    label: "安全重視",
    weights: {
      gradient: 0.05, surface_q: 0.05, stop_density: 0.2, night: 0.1,
      car_stress: 0.3, accident: 0.3, wind: 0.0,
    },
  },
];

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
}

export default function RouteSettingsPanel({
  hardFilters,
  onHardFiltersChange,
  routePreference,
  onRoutePreferenceChange,
  overrideEnabled,
  onOverrideEnabledChange,
}: RouteSettingsPanelProps) {
  const catalog = useAxisCatalog();
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

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

  const PRESETS: readonly Preset[] = [
    { label: "バランス", weights: catalog.defaultWeights },
    ...NON_DEFAULT_PRESETS,
  ];

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

  function applyPreset(preset: Preset) {
    // 未言及の軸はカタログの既定重みで補い、全既知axis_idを常に埋めた状態でbackendへ送る
    // （T268コメント参照、PRESET定義側の部分指定を許すための必須処理）。
    const merged: RoutePreferenceWeights = { ...catalog.defaultWeights, ...preset.weights };
    setLastWeights((prev) => {
      const next = { ...prev };
      for (const [axisId, weight] of Object.entries(merged)) {
        if (weight > 0) next[axisId] = weight;
      }
      return next;
    });
    handlePreferenceChange(merged);
  }

  const total = totalWeight(routePreference);

  return (
    <div className="flex flex-col gap-3">
      <div className={styles.presets}>
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            className={styles.presetButton}
            onClick={() => applyPreset(preset)}
          >
            {preset.label}
          </button>
        ))}
      </div>

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
          {catalog.axes.map(({ axisId, label }) => {
            const weight = routePreference[axisId] ?? 0;
            if (weight <= 0 || total <= 0) return null;
            const pct = (weight / total) * 100;
            return (
              <div
                key={axisId}
                className={styles.stackSegment}
                data-axis={axisId}
                style={{ width: `${pct}%` }}
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
