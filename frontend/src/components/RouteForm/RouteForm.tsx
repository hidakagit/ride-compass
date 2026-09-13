"use client";

import * as Tabs from "@radix-ui/react-tabs";
import type { PinRole } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { isMaxRoutesRelevant } from "./useRouteFormSubmit";
import styles from "./RouteForm.module.css";

export type RouteMode = "loop" | "destination";

/** 「ルート設定」区分のタブ。タブ列と選択状態はpage.tsxが持ち（見出し行に置くため）、
 * ここは各タブの中身だけを描く。 */
export type SettingsTab = "generate" | "weights" | "exclusions";

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
  /** 目的地を置いてあるか。 */
  destinationSet: boolean;
  onDestinationClear: () => void;
  /** 出発地を地図で置き直してあるか（falseなら現在地のまま）。 */
  originManual: boolean;
  /** 出発地を現在地へ戻す（現在地の取得もこの操作が兼ねる）。 */
  onOriginReset: () => void;
  /** いま地図のタップで置ける役割。nullなら地図を触ってもピンは増えない。 */
  armedPinRole: PinRole | null;
  /** 行の操作で武装する／やめる（同じ役割をもう一度押すと解除）。 */
  onArmPinRole: (role: PinRole | null) => void;
  /** 「重み」タブの中身（RouteSettingsPanelを含む要素一式）。「ルート設定」区分は
   * 「条件」（本コンポーネントの距離・候補数等）・「重み」・「除外」の3タブへ分ける。
   * タブ列（Tabs.List）と「ルート生成」ボタンはこのコンポーネントの外（page.tsx:
   * 「ルート設定」見出し行）にあり、検証ロジックは`useRouteFormSubmit`が持つ
   * （本コンポーネントは入力欄と各タブの中身のみ）。 */
  weightsPanel: React.ReactNode;
  /** 「除外」タブの中身（HardFilterPanel）。将来の除外条件もこのタブへ足す。 */
  exclusionsPanel: React.ReactNode;
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
  destinationSet,
  onDestinationClear,
  originManual,
  onOriginReset,
  armedPinRole,
  onArmPinRole,
  weightsPanel,
  exclusionsPanel,
}: RouteFormProps) {
  const maxRoutesRelevant = isMaxRoutesRelevant(routeMode, waypointCount);

  function stepMaxRoutes(delta: number) {
    const next = Math.min(MAX_ROUTES, Math.max(1, Number(maxRoutes) + delta));
    onMaxRoutesChange(String(next));
  }

  // 出発地・経由地・目的地は同じ形の行で並べる（役割が同じ「地点を置く」操作のため）。
  // 行頭の印は地図のマーカーと同じ色・同じ字で、行とピンを見た目で結ぶ。
  // 武装は1つだけで、押している行以外は自動的に解除される（page.tsx: armedPinRole）。
  function renderPointRow(
    role: PinRole,
    label: string,
    mark: { text: string; background?: string },
    value: string,
    armLabel: string,
    extra?: React.ReactNode,
    /** 武装中に値の代わりに出す文言。置いた数を隠さないため、経由地は件数を添える。 */
    armedHint: string = "地図をタップ"
  ) {
    const armed = armedPinRole === role;
    return (
      <div className={styles.pointRow} data-armed={armed}>
        <span aria-hidden="true" className={styles.pointMark} style={{ background: mark.background }}>
          {mark.text}
        </span>
        <span className={styles.pointLabel}>{label}</span>
        <span className={styles.pointValue}>{armed ? armedHint : value}</span>
        {extra}
        <button
          type="button"
          className={armed ? styles.pointActionArmed : styles.pointAction}
          aria-pressed={armed}
          aria-label={armed ? `${label}の指定をやめる` : `${label}を${armLabel}`}
          onClick={() => onArmPinRole(armed ? null : role)}
        >
          {armed ? "やめる" : armLabel}
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* forceMount+data-stateでの表示切替（page.module.css: .outcomeTabPanelと同じ方式）。
          候補数等はpage.tsx側の制御stateのため非表示中も値は失われないが、
          重みタブ（RouteSettingsPanel）はドラッグ中の帯グラフ・チェックOFF前の
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
            <div className={styles.pointRows}>
              {renderPointRow(
                "origin",
                "出発地",
                { text: "●", background: "#e11d48" },
                originManual ? "地図で指定" : "現在地",
                "地図で選ぶ",
                originManual ? (
                  <button
                    type="button"
                    className={styles.pointSubAction}
                    aria-label="出発地を現在地に戻す"
                    onClick={onOriginReset}
                  >
                    現在地に戻す
                  </button>
                ) : undefined,
              )}
              {renderPointRow(
                "waypoint",
                "経由地",
                { text: "●", background: "#2563eb" },
                waypointCount > 0 ? `${waypointCount}地点` : "なし",
                "追加",
                waypointCount > 0 ? (
                  <button
                    type="button"
                    className={styles.pointClear}
                    aria-label="経由地をクリア"
                    onClick={onWaypointsClear}
                  >
                    ✕
                  </button>
                ) : undefined,
                waypointCount > 0 ? `地図をタップ（${waypointCount}地点）` : "地図をタップ",
              )}
              {renderPointRow(
                "destination",
                "目的地",
                { text: "🏁" },
                destinationSet ? "地図で指定" : "未設定",
                destinationSet ? "置き直す" : "地図で選ぶ",
                destinationSet ? (
                  <button
                    type="button"
                    className={styles.pointClear}
                    aria-label="目的地を解除"
                    onClick={onDestinationClear}
                  >
                    ✕
                  </button>
                ) : undefined,
              )}
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

      <Tabs.Content value="exclusions" forceMount className={styles.tabPanel}>
        {exclusionsPanel}
      </Tabs.Content>
    </div>
  );
}
