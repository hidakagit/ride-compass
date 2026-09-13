"use client";

import * as Tabs from "@radix-ui/react-tabs";
import InfoPopover from "@/components/Map/InfoPopover";
import {
  ORIGIN_MARK_COLOR,
  ORIGIN_MARK_FALLBACK_COLOR,
  PIN_MARK_BACKGROUND,
  pinMarkHtml,
} from "@/components/Map/pinMarks";
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
  /** 現在地を実際に取得できているか。falseの間は地図のピンと同じく印を灰色にする
   * （位置が既定値のままであることを、行と地図で同じ色で示す）。 */
  originLocated: boolean;
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
  originLocated,
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
  // 行頭の印は**地図のピンと同じ図形**（pinMarks.ts）で、行とピンを見た目で結ぶ。
  // 武装は1つだけで、押している行以外は自動的に解除される（page.tsx: armedPinRole）。
  function renderPointRow(
    role: PinRole,
    label: string,
    markLabel: string | undefined,
    value: string,
    armLabel: string,
    extra?: React.ReactNode,
    /** 武装中に値の代わりに出す文言。置いた数を隠さないため、経由地は件数を添える。 */
    armedHint: string = "地図をタップ"
  ) {
    const armed = armedPinRole === role;
    return (
      <div className={styles.pointRow} data-armed={armed}>
        {/* 行全体が「その地点を置く」1つの押下領域。押す場所を探させず、行の幅も詰まる。
            解除（✕）・現在地に戻すは別の操作なので、入れ子にせず行の外側へ並べる。 */}
        <button
          type="button"
          className={styles.pointMain}
          aria-pressed={armed}
          aria-label={armed ? `${label}の指定をやめる` : `${label}を${armLabel}`}
          onClick={() => onArmPinRole(armed ? null : role)}
        >
          {/* 地図のピンと同じ図形をそのまま出す（pinMarks.tsの定数だけを組み立てた文字列で、
              外部の入力は入らない）。同じものを2度描くと、片方だけ直したときに行とピンが
              違う見た目になる。 */}
          <span
            aria-hidden="true"
            className={styles.pointMark}
            style={{ background: PIN_MARK_BACKGROUND[role] }}
            dangerouslySetInnerHTML={{
              __html: pinMarkHtml(role, {
                label: markLabel,
                size: 13,
                color: originLocated ? ORIGIN_MARK_COLOR : ORIGIN_MARK_FALLBACK_COLOR,
              }),
            }}
          />
          <span className={styles.pointLabel}>{label}</span>
          <span className={styles.pointValue}>{armed ? armedHint : value}</span>
          <span aria-hidden="true" className={armed ? styles.pointHintArmed : styles.pointHint}>
            {armed ? "やめる" : armLabel}
          </span>
        </button>
        {extra}
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
        {/* モードと候補数は同じ行に置く。候補数はどちらのモードでも効く共通の条件で、
            モードごとの入力（距離／地点）とは別の階層にある。 */}
        <div className={styles.modeRow}>
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
          {/* 経由地があるとbackendは常に1件へ固定する（route_generator.py:
              generate_via_waypoints）。押せない状態で残す——消えると壊れて見えるうえ、
              複数候補へ広げる予定があるため置き場を動かさない。理由は隣の(i)の奥。 */}
          <div className={styles.stepperField} data-disabled={!maxRoutesRelevant}>
            <span className={styles.stepperLabel}>候補数</span>
            {!maxRoutesRelevant && (
              <InfoPopover
                triggerClassName={styles.stepperInfo}
                triggerAriaLabel="候補数を変えられない理由"
                contentClassName={styles.stepperInfoPopover}
              >
                経由地を置いている間は、その地点を通る経路を1本だけ引きます。候補数は経由地を
                消すと使えます。
              </InfoPopover>
            )}
            <div className={styles.stepper}>
              <button
                type="button"
                className={styles.stepperButton}
                onClick={() => stepMaxRoutes(-1)}
                disabled={!maxRoutesRelevant || Number(maxRoutes) <= 1}
                aria-label="候補数を減らす"
              >
                ‹
              </button>
              <span className={styles.stepperValue}>{maxRoutesRelevant ? `${maxRoutes}件` : "1件"}</span>
              <button
                type="button"
                className={styles.stepperButton}
                onClick={() => stepMaxRoutes(1)}
                disabled={!maxRoutesRelevant || Number(maxRoutes) >= MAX_ROUTES}
                aria-label="候補数を増やす"
              >
                ›
              </button>
            </div>
          </div>
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
                undefined,
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
                waypointCount > 0 ? String(waypointCount) : undefined,
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
                undefined,
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
