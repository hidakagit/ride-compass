"use client";

import { useState } from "react";
import Disclosure from "@/components/Disclosure/Disclosure";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import SystemStatusPanel from "@/components/SystemStatusPanel/SystemStatusPanel";
import WeightPanel, { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "@/components/WeightPanel/WeightPanel";
import CarStressRecipePanel from "@/components/CarStressRecipePanel/CarStressRecipePanel";
import RoadSuitabilityRecipePanel from "@/components/RoadSuitabilityRecipePanel/RoadSuitabilityRecipePanel";
import MotorVehicleDensityRecipePanel from "@/components/MotorVehicleDensityRecipePanel/MotorVehicleDensityRecipePanel";
import {
  DEFAULT_CAR_STRESS_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
} from "@/components/Map/carStressExpression";
import { axisMaterials, PRIMARY_ATTRIBUTE_LABELS } from "@/components/Map/primaryAttributes";
import AxisStudio from "@/components/AxisStudio/AxisStudio";
import { useRecipeOverride } from "@/hooks/useRecipeOverride";
import { useStoredJsonState } from "@/hooks/useStoredState";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import type { CarStressRecipeOverride, MotorVehicleDensityRecipeOverride, RoadSuitabilityRecipeOverride, RoutePreferenceWeights, ScoringWeights } from "@/types/route";
import styles from "./admin.module.css";

const LEGEND_FILTER_DEBOUNCE_MS = 250;

// 軸スタジオ・研究モード・開発者向け機能をまとめた独立URLの管理画面（改善計画T270、
// 目論見書4章「軸スタジオ」）。一般向けメインページ（/）とはURLレベルで分離しており、
// 権限制御（改善計画T272、2026-08-24完了）はこのルーティング境界（src/proxy.ts、
// matcher: ["/admin","/admin/:path*"]）にHTTP Basic認証として敷いている
// （環境変数ADMIN_BASIC_AUTH_USERNAME/PASSWORD未設定時は常に到達不可）。
// 研究モード・評価重み・レシピの各stateはlocalStorage経由でメインページと共有する
// ——同じキーでuseStoredJsonState/useRecipeOverrideを呼ぶことで、ここでの編集が
// 次回メインページを開いたとき/再読み込みしたときに反映される。同一タブでのリアルタイム
// 同期ではない点はlib/researchMode.ts等の既存パターンと同じ）。
export default function AdminPage() {
  const researchEnabled = useResearchEnabled();
  const debugEnabled = useDebugEnabled();
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);

  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredJsonState(
    "ridecompass:weight-override-enabled",
    false
  );
  const [scoringWeights, setScoringWeights] = useStoredJsonState<ScoringWeights>(
    "ridecompass:scoring-weights",
    DEFAULT_SCORING_WEIGHTS
  );
  const [routePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    "ridecompass:route-preference",
    DEFAULT_ROUTE_PREFERENCE
  );

  const {
    overrideEnabled: carStressRecipeOverrideEnabled,
    setOverrideEnabled: setCarStressRecipeOverrideEnabled,
    recipe: carStressRecipe,
    setRecipe: setCarStressRecipe,
  } = useRecipeOverride<CarStressRecipeOverride>(
    DEFAULT_CAR_STRESS_RECIPE,
    LEGEND_FILTER_DEBOUNCE_MS,
    "ridecompass:car-stress-recipe"
  );
  const {
    overrideEnabled: roadSuitabilityRecipeOverrideEnabled,
    setOverrideEnabled: setRoadSuitabilityRecipeOverrideEnabled,
    recipe: roadSuitabilityRecipe,
    setRecipe: setRoadSuitabilityRecipe,
  } = useRecipeOverride<RoadSuitabilityRecipeOverride>(
    DEFAULT_ROAD_SUITABILITY_RECIPE,
    LEGEND_FILTER_DEBOUNCE_MS,
    "ridecompass:road-suitability-recipe"
  );
  const {
    overrideEnabled: motorVehicleDensityRecipeOverrideEnabled,
    setOverrideEnabled: setMotorVehicleDensityRecipeOverrideEnabled,
    recipe: motorVehicleDensityRecipe,
    setRecipe: setMotorVehicleDensityRecipe,
  } = useRecipeOverride<MotorVehicleDensityRecipeOverride>(
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    LEGEND_FILTER_DEBOUNCE_MS,
    "ridecompass:motor-vehicle-density-recipe"
  );

  // 改善計画T168: 区間難易度の重み行の直下へ、その軸が参照する一次属性の一覧を出す
  // （page.tsxのrenderAxisMaterialsExtraを移設）。
  function renderAxisMaterialsExtra(axisId: string) {
    const materials = axisMaterials(axisId);
    if (materials.length === 0) return null;
    return (
      <p className={styles.recipeSharedMaterialHeading}>
        材料: {materials.map((attrId) => PRIMARY_ATTRIBUTE_LABELS[attrId]).join("・")}
      </p>
    );
  }

  // page.tsxのrenderCarStressRecipeExtraを移設。道路適正・自動車密度（車の圧迫感が
  // 参照する共有材料）と車ストレスレシピ本体を、重み行の直下へ差し込む。
  function renderCarStressRecipeExtra() {
    return (
      <>
        <div className={styles.recipeSharedMaterialGroup}>
          <p className={styles.recipeSharedMaterialHeading}>
            レシピ[一次情報→二次情報の変換式]・共有材料[車の圧迫感が参照]
          </p>
          <div className={styles.card}>
            <RoadSuitabilityRecipePanel
              overrideEnabled={roadSuitabilityRecipeOverrideEnabled}
              onOverrideEnabledChange={setRoadSuitabilityRecipeOverrideEnabled}
              recipe={roadSuitabilityRecipe}
              onRecipeChange={setRoadSuitabilityRecipe}
            />
          </div>
          <div className={styles.card}>
            <MotorVehicleDensityRecipePanel
              overrideEnabled={motorVehicleDensityRecipeOverrideEnabled}
              onOverrideEnabledChange={setMotorVehicleDensityRecipeOverrideEnabled}
              recipe={motorVehicleDensityRecipe}
              onRecipeChange={setMotorVehicleDensityRecipe}
            />
          </div>
        </div>
        <div className={styles.recipeDependentAxes}>
          <div className={styles.card}>
            <CarStressRecipePanel
              overrideEnabled={carStressRecipeOverrideEnabled}
              onOverrideEnabledChange={setCarStressRecipeOverrideEnabled}
              recipe={carStressRecipe}
              onRecipeChange={setCarStressRecipe}
              roadSuitabilityRecipe={
                roadSuitabilityRecipeOverrideEnabled ? roadSuitabilityRecipe : DEFAULT_ROAD_SUITABILITY_RECIPE
              }
              motorVehicleDensityRecipe={
                motorVehicleDensityRecipeOverrideEnabled
                  ? motorVehicleDensityRecipe
                  : DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE
              }
            />
          </div>
        </div>
      </>
    );
  }

  function renderPreferenceFieldExtra(axisId: string) {
    return (
      <>
        {renderAxisMaterialsExtra(axisId)}
        {axisId === "car_stress" && renderCarStressRecipeExtra()}
      </>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>軸スタジオ・研究/開発者ツール</h1>
        <p className={styles.subtitle}>
          このページは独立URL（/admin）の管理画面です（改善計画T270）。一般向けルート設定は
          トップページ（/）を使ってください。評価重み・レシピの設定はブラウザのlocalStorage
          経由でトップページと共有されます。
        </p>
      </header>

      <section className={styles.section}>
        <h2 className={styles.sectionHeading}>評価軸（軸スタジオ）</h2>
        <AxisStudio />
      </section>

      <Disclosure
        className={styles.section}
        triggerClassName={styles.sectionSummary}
        bodyClassName={styles.sectionBody}
        summary={<h2 className={styles.sectionHeading}>研究</h2>}
        defaultOpen
      >
        <ResearchPanel />
        {researchEnabled && (
          <div className={styles.card}>
            <WeightPanel
              overrideEnabled={weightOverrideEnabled}
              onOverrideEnabledChange={setWeightOverrideEnabled}
              scoringWeights={scoringWeights}
              onScoringWeightsChange={setScoringWeights}
              routePreference={routePreference}
              onRoutePreferenceChange={setRoutePreference}
              renderPreferenceFieldExtra={renderPreferenceFieldExtra}
            />
          </div>
        )}
        {!researchEnabled && (
          <p className={styles.hint}>
            研究モードは現在OFFです。上のチェックボックスで有効にすると評価重みの調整パネルが
            現れます。
          </p>
        )}
      </Disclosure>

      <Disclosure
        className={styles.section}
        triggerClassName={styles.sectionSummary}
        bodyClassName={styles.sectionBody}
        summary={<h2 className={styles.sectionHeading}>開発者</h2>}
      >
        <div className={styles.systemRow}>
          <div className={styles.debugControl}>
            <DebugPanel />
            <button type="button" onClick={() => setSystemStatusOpen((v) => !v)} aria-pressed={systemStatusOpen}>
              {systemStatusOpen ? "システム状況を隠す" : "システム状況を表示"}
            </button>
          </div>
          <BackendStatus />
        </div>
        {debugEnabled && (
          // 改善計画T278レビュー指摘の修正（2026-08-24）: デバッグログ（地図の表示
          // イベント・API呼び出しのライブログ）はDebugConsole自体が地図インスタンスに
          // 紐づく情報のため、地図の無いこのページへ置いても記録先lib/debugLog.tsが
          // タブ間で共有されず実質機能しなかった。「/admin=デバッグモードの設定」
          // 「/=地図を操作しながら見るライブログ本体」という役割分担にし、閲覧はトップ
          // ページ（/）の「開発者」ブロックで行う（デバッグモードのON/OFF自体は上の
          // DebugPanelがlocalStorage経由でトップページと共有する）。
          <p className={styles.hint}>デバッグログの表示はトップページ（/）の「開発者」ブロックで行えます。</p>
        )}
        <SystemStatusPanel open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
      </Disclosure>
    </div>
  );
}
