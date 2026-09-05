"use client";

import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { isMaxRoutesRelevant } from "./useRouteFormSubmit";
import styles from "./RouteForm.module.css";

export type RouteMode = "loop" | "destination";
export type DestinationButtonState = "unset" | "armed" | "set";

type SettingsTab = "generate" | "weights";

interface RouteFormProps {
  /** 距離入力の現在値（文字列のまま）。生成条件のdirty判定（page.tsx）に使うため親が持つ */
  distance: string;
  onDistanceChange: (value: string) => void;
  /** 候補件数入力の現在値（文字列のまま）。距離と同じ理由で親が持つ。周回モードと、
   * 目的地モードで経由地が無い場合に意味を持つ（経由地を伴う目的地ルートはbackendが
   * 常に1件へ固定し無視する）。 */
  maxRoutes: string;
  onMaxRoutesChange: (value: string) => void;
  /** 周回（距離指定）/目的地（経由地・目的地を地図で指定）モードの切り替え。距離入力・
   * 候補数入力と同じ場所に置く。 */
  routeMode: RouteMode;
  onRouteModeChange: (mode: RouteMode) => void;
  waypointCount: number;
  onWaypointsClear: () => void;
  destinationState: DestinationButtonState;
  onDestinationButtonClick: () => void;
  /** 「重みづけ」タブの中身（RouteSettingsPanelを含む要素一式）。「ルート設定」区分は
   * 「生成条件」（本コンポーネントの距離・候補数等）と「重みづけ」の2タブへ分ける。
   * 「ルート生成」ボタンはこのコンポーネントの外（page.tsx: 「ルート設定」見出し行）に
   * 置き、検証ロジックは`useRouteFormSubmit`が持つ（本コンポーネントは入力欄のみ）。 */
  weightsPanel: React.ReactNode;
}

const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;
const MAX_ROUTES = routeGenerateConfig.max_routes;

export default function RouteForm({
  distance,
  onDistanceChange,
  maxRoutes,
  onMaxRoutesChange,
  routeMode,
  onRouteModeChange,
  waypointCount,
  onWaypointsClear,
  destinationState,
  onDestinationButtonClick,
  weightsPanel,
}: RouteFormProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("generate");
  const maxRoutesRelevant = isMaxRoutesRelevant(routeMode, waypointCount);

  function stepMaxRoutes(delta: number) {
    const next = Math.min(MAX_ROUTES, Math.max(1, Number(maxRoutes) + delta));
    onMaxRoutesChange(String(next));
  }

  const destinationButtonLabel =
    destinationState === "set"
      ? "目的地を解除"
      : destinationState === "armed"
        ? "地図をタップして目的地を指定（タップでキャンセル）"
        : "目的地を設定（地図をタップ）";
  const destinationButtonClassName =
    destinationState === "set"
      ? styles.destinationChipSet
      : destinationState === "armed"
        ? styles.destinationChipArmed
        : styles.destinationChip;

  return (
    <div>
      <Tabs.Root value={activeTab} onValueChange={(value) => setActiveTab(value as SettingsTab)}>
        <Tabs.List className={styles.tabList} aria-label="ルート設定">
          <Tabs.Trigger className={styles.tabTrigger} value="generate">
            生成条件
          </Tabs.Trigger>
          <Tabs.Trigger className={styles.tabTrigger} value="weights">
            重みづけ
          </Tabs.Trigger>
        </Tabs.List>

        {/* forceMount+data-stateでの表示切替（page.module.css: .outcomeTabPanelと同じ方式）。
            候補数等はpage.tsx側の制御stateのため非表示中も値は失われないが、
            重みづけタブ（RouteSettingsPanel）はドラッグ中の帯グラフ・チェックOFF前の
            重み記憶をローカルstateで持つため、タブ切替のたびにアンマウントすると失われる。 */}
        <Tabs.Content value="generate" forceMount className={styles.tabPanel}>
          <div className={styles.modeToggle} role="group" aria-label="ルート生成モード">
            <button
              type="button"
              onClick={() => onRouteModeChange("loop")}
              aria-pressed={routeMode === "loop"}
              className={routeMode === "loop" ? styles.modeButtonActive : styles.modeButton}
            >
              周回
            </button>
            <button
              type="button"
              onClick={() => onRouteModeChange("destination")}
              aria-pressed={routeMode === "destination"}
              className={routeMode === "destination" ? styles.modeButtonActive : styles.modeButton}
            >
              目的地
            </button>
          </div>

          <div className={styles.fieldsColumn}>
            {routeMode === "loop" ? (
              <div className={styles.sliderField}>
                <label htmlFor="route-form-distance" className={styles.sliderLabel}>
                  距離
                </label>
                <input
                  id="route-form-distance"
                  type="range"
                  min={1}
                  max={MAX_DISTANCE_KM}
                  step={1}
                  value={distance}
                  onChange={(e) => onDistanceChange(e.target.value)}
                  className={styles.slider}
                />
                <span className={styles.sliderValue}>{distance}km</span>
              </div>
            ) : (
              <div className={styles.destinationSummary}>
                {waypointCount > 0 && (
                  <span className={styles.summaryChip}>
                    📍{waypointCount}
                    <button type="button" onClick={onWaypointsClear} aria-label="経由地をクリア">
                      ✕
                    </button>
                  </span>
                )}
                <button
                  type="button"
                  onClick={onDestinationButtonClick}
                  aria-label={destinationButtonLabel}
                  title={destinationButtonLabel}
                  className={destinationButtonClassName}
                >
                  🏁
                </button>
              </div>
            )}
            {maxRoutesRelevant && (
              <div className={styles.stepperField}>
                <span className={styles.stepperLabel}>候補数</span>
                <div className={styles.stepper}>
                  <button
                    type="button"
                    className={styles.stepperButton}
                    onClick={() => stepMaxRoutes(-1)}
                    disabled={Number(maxRoutes) <= 1}
                    aria-label="候補数を減らす"
                  >
                    ‹
                  </button>
                  <span className={styles.stepperValue}>{maxRoutes}件</span>
                  <button
                    type="button"
                    className={styles.stepperButton}
                    onClick={() => stepMaxRoutes(1)}
                    disabled={Number(maxRoutes) >= MAX_ROUTES}
                    aria-label="候補数を増やす"
                  >
                    ›
                  </button>
                </div>
              </div>
            )}
          </div>
        </Tabs.Content>

        <Tabs.Content value="weights" forceMount className={styles.tabPanel}>
          {weightsPanel}
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
