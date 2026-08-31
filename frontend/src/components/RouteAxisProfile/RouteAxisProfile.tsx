"use client";

import * as Popover from "@radix-ui/react-popover";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { InfoIcon } from "@/components/Map/icons";
import { rampColorForBand } from "@/components/Map/axisLayers";
import { getRouteStyleMode, type RouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
// 改善計画T518: 色分け選択チップ・凡例ポップオーバーの外枠はRouteSettingsPanel.module.css
// のクラスをそのままimportして流用する（page.tsxがMapLayersPanel.module.cssのクラスを
// 再利用している既存の「別コンポーネントのCSS Moduleクラスをそのままimportして流用する」
// 慣習を踏襲）。ただしトグルボタン自体（.legendToggle相当）だけは、RouteSettingsPanel側で
// 「重みON/OFF」用にaria-pressedへ状態を出しているクラスを直接共有すると、ここで
// 「選択中/非選択中」用の見た目（aria-pressed="true"時の塗りつぶし）を追加した際に
// RouteSettingsPanel側の重みON表示（ほぼ常時true）まで意図せず変えてしまう。そのため
// トグルボタンだけは同じCSS Modulesファイルを共有せず、下記.axisToggleとして独自定義する
// （legendChip/legendDot/legendInfoButton/legendInfoPopover等の状態を持たない構造的な
// クラスは共有して問題ない）。
import legendStyles from "@/components/RouteSettingsPanel/RouteSettingsPanel.module.css";
import styles from "./RouteAxisProfile.module.css";

interface RouteAxisProfileProps {
  /** 表示対象の軸一覧（順序・ラベルの正本）。呼び出し側がuseAxisCatalog().axesを
   * route_preferenceの重み>0で絞り込んで渡す。 */
  axes: readonly PreferenceAxisDef[];
  /** RouteCandidate.axis_difficulties（axis_id→difficulty 0-100の距離加重平均）。
   * 評価できなかった軸はキー自体を持たない。 */
  axisDifficulties: Record<string, number>;
  /** RouteCandidate.overall_difficulty（内訳の合計、絶対基準0-100）。 */
  overallDifficulty: number | null;
  /** RouteCandidate.total_score（おすすめ度、候補間の相対スコア。overallDifficultyとは
   * 別指標のため内訳には含めず並記のみ）。 */
  totalScore: number | null;
  /** 内訳の重み付き寄与度計算に使う重み（axis_id→重み。生成時点の値を渡すこと）。 */
  weights: RoutePreferenceWeights;
  /** 軸id→色ドットの色（RouteSettingsPanelのstackBarColorForIndexと同じ計算をpage.tsxが
   * 行い、同じ軸なら両パネルで同じ色になるようにする）。 */
  axisColors: Record<string, string>;
  routeStyleModes: readonly RouteStyleMode[];
  routeStyleModeId: RouteStyleModeId;
  onRouteStyleModeChange: (id: RouteStyleModeId) => void;
  hiddenLegendKeys: readonly string[];
  onToggleLegendKey: (key: string) => void;
}

// 「総合難易度」は特定の軸に紐づかない合成モードのため、軸カタログ由来の色（axisColors）を
// 持たない。地図の「ルート」候補線の非選択色（#64748b、MapView.tsx: drawBaseRoutes）と
// 同じ中立グレーを流用し、「特定の軸ではなく全体を指す」ことを色でも示す。
const TOTAL_DOT_COLOR = "#64748b";

// difficulty(0-100)をaxisLayers.tsの共有ランプ配色（緑→黄→橙→赤、RAMP_COLOR_ANCHORS）へ
// 写像する。rampColorForBand(index, bandCount)はbandCount段階中index番目の色を
// t=index/(bandCount-1)でRAMP_COLOR_ANCHORS上を線形補間して返す設計のため、
// bandCount=101・index=Math.round(value)とすればt=value/100に一致し、地図の段階配色と
// 完全に同じ配色系統のまま0-100の連続値をそのまま色へ変換できる。
function colorForDifficulty(value: number): string {
  const clamped = Math.min(100, Math.max(0, value));
  return rampColorForBand(Math.round(clamped), 101);
}

// ルート全体のaxis_difficultiesを軸ごとの横棒グラフ一覧として表示する（改善計画T400節4・
// T402の可視化形式を踏襲）。改善計画T518でこのコンポーネントへ「地図の色分け選択」
// 「凡例の表示設定」を統合した（旧page.tsx: renderRouteColorSectionBody、「ルート結果
// パネルの全タブに残り続ける」「ルート選択タブと独立した情報を持たない」という指摘を受け、
// 「ルート選択」タブ内・選択中候補の直後にこのコンポーネント1つへ集約した）。
export default function RouteAxisProfile({
  axes,
  axisDifficulties,
  overallDifficulty,
  totalScore,
  weights,
  axisColors,
  routeStyleModes,
  routeStyleModeId,
  onRouteStyleModeChange,
  hiddenLegendKeys,
  onToggleLegendKey,
}: RouteAxisProfileProps) {
  // 軸カタログの並び順のうち、このルートで実際に評価できた軸だけを表示する
  // （axis_difficultiesにキーが無い＝データ無しで評価不能、という規約はRouteSegmentDetail
  // と共通。domain/route.py: RouteCandidate docstring参照）。
  const rows = axes.filter((axis) => axisDifficulties[axis.axisId] != null);

  if (rows.length === 0) {
    return <p className={styles.empty}>このルートで表示できる評価軸データがありません</p>;
  }

  // domain/difficulty.py: composite_difficulty（sum(score*weight)/sum(weight)、有効な軸の
  // みで正規化）と同じ考え方をfrontend側で再現する。表示対象の全軸のcontributionを合計
  // すると、backend側の丸め差を除きoverallDifficultyにほぼ一致する。
  const weightSum = rows.reduce((sum, axis) => sum + Math.max(0, weights[axis.axisId] ?? 0), 0);
  function contribution(axisId: string): number {
    const raw = axisDifficulties[axisId];
    if (weightSum <= 0) return raw; // 重み情報が無い/全0の縮退ケースは素の値へフォールバック
    return (raw * Math.max(0, weights[axisId] ?? 0)) / weightSum;
  }

  const currentMode = getRouteStyleMode(routeStyleModes, routeStyleModeId);
  const isTotalSelected = routeStyleModeId === "difficulty";

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <span className={styles.hint}>地図の色分け</span>
        {/* RouteSettingsPanel.tsx: 「重み配分」見出し脇のstackBarLegendTriggerと同じ
            パターン（アイコン→ポップオーバーでリスト表示）。中身だけ読み取り専用の%表示
            ではなくChecksbox（表示/非表示トグル）にしている。 */}
        <Popover.Root>
          <Popover.Trigger asChild>
            <button type="button" className={legendStyles.stackBarLegendTrigger} aria-label="凡例の表示設定">
              <InfoIcon />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content className={legendStyles.legendInfoPopover} side="left" align="start" sideOffset={6}>
              <ul className={legendStyles.stackBarLegendList}>
                {currentMode.legend.map((entry) => {
                  const visible = !hiddenLegendKeys.includes(entry.key);
                  return (
                    <li key={entry.key} className={legendStyles.stackBarLegendItem}>
                      <Checkbox checked={visible} onCheckedChange={() => onToggleLegendKey(entry.key)} aria-label={entry.label} />
                      <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: entry.color }} />
                      <span className={legendStyles.stackBarLegendLabel}>{entry.label}</span>
                    </li>
                  );
                })}
              </ul>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>

      {/* 総合難易度は内訳（下記）の合計そのものであり内訳の1項目ではないため、別枠の
          「合計」として分離する（ユーザー指摘2026-09-01「内訳に総合難易度が入っているのは
          なぜ？」）。おすすめ度（total_score、候補間の相対スコア）と総合難易度
          （overall_difficulty、絶対基準の軸重み付き合成値）は別指標のため両方を並記し、
          片方をもう片方の内訳として扱わない（domain/route.py: RouteCandidate/
          RouteScoreComponentのdocstring参照）。 */}
      <div className={styles.totalRow}>
        <span className={legendStyles.legendChip}>
          <button
            type="button"
            className={styles.axisToggle}
            aria-pressed={isTotalSelected}
            aria-label="総合難易度で地図を色分け"
            onClick={() => onRouteStyleModeChange("difficulty")}
          >
            <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: TOTAL_DOT_COLOR }} />
            <span>総合難易度</span>
          </button>
        </span>
      </div>
      {(totalScore != null || overallDifficulty != null) && (
        <div className={styles.scores}>
          {totalScore != null && (
            <span className={styles.scoreItem}>
              <span className={styles.scoreValue}>{Math.round(totalScore)}</span>
              <span className={styles.scoreLabel}>点 おすすめ度</span>
            </span>
          )}
          {overallDifficulty != null && (
            <span className={styles.scoreItem}>
              <span className={styles.scoreValue}>{Math.round(overallDifficulty)}</span>
              <span className={styles.scoreLabel}>/100 総合難易度</span>
            </span>
          )}
        </div>
      )}
      <p className={styles.scoreHint}>
        おすすめ度は候補間の相対評価、総合難易度は距離・軸重みを反映した絶対値（下の内訳の合計）です。
      </p>

      <div className={styles.breakdown}>
        <p className={styles.hint}>内訳（重み付き寄与度）</p>
        <ul className={styles.list}>
          {rows.map((axis) => {
            const raw = axisDifficulties[axis.axisId];
            const value = contribution(axis.axisId);
            const active = routeStyleModeId === axis.axisId;
            // 改善計画T518・実機確認で発覚: routeStyleModesは軸カタログのsupports_route_
            // coloring===trueの軸だけから生成される（car_stress・accident・night・
            // bicycle_infra_quality等は対象外）。そうした軸のチップをクリック可能にすると
            // 「対応する地図色分けが存在しないid」でonRouteStyleModeChangeを呼んでしまい、
            // page.tsx側のフォールバックeffect（該当モードが無ければ先頭モードへ戻す）が
            // 即座に選択を巻き戻すため、クリックしても何も起きたように見えない無反応の
            // ボタンになっていた。対応する地図色分けが無い軸は非活性表示にする。
            const colorable = routeStyleModes.some((mode) => mode.id === axis.axisId);
            return (
              <li key={axis.axisId} className={styles.row}>
                {colorable ? (
                  <span className={legendStyles.legendChip}>
                    <button
                      type="button"
                      className={styles.axisToggle}
                      aria-pressed={active}
                      aria-label={`${axis.label}で地図を色分け`}
                      onClick={() => onRouteStyleModeChange(axis.axisId)}
                    >
                      <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: axisColors[axis.axisId] ?? TOTAL_DOT_COLOR }} />
                      <span>{axis.label}</span>
                    </button>
                  </span>
                ) : (
                  <span className={legendStyles.legendChip} title="この軸は地図の色分けに対応していません">
                    <span className={`${styles.axisToggle} ${styles.axisLabel}`}>
                      <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: axisColors[axis.axisId] ?? TOTAL_DOT_COLOR }} />
                      <span>{axis.label}</span>
                    </span>
                  </span>
                )}
                <span className={styles.track}>
                  <span
                    className={styles.bar}
                    style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: colorForDifficulty(raw) }}
                  />
                </span>
                <span className={styles.value}>{Math.round(value)}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
