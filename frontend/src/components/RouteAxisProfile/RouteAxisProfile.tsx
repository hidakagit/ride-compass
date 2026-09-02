"use client";

import * as Popover from "@radix-ui/react-popover";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { InfoIcon, MapAppearanceIcon } from "@/components/Map/icons";
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

// 改善計画T524（T518コードレビューSIMPLIFY指摘）: 「legendChip > 色ドット + ラベル」という
// 構造が総合難易度行・各軸行で重複していたため、共有サブコンポーネントへ抽出する。
// 改善計画T545フォローアップ（ユーザー指摘「タブ内の地図の色分けが切り替えられない」）:
// 以前はsupports_route_coloring===falseの軸（car_stress・accident・night・
// bicycle_infra_quality等）もこのチップ列に非活性表示（cursor:defaultのみで区別、
// クリックしても無反応）で並べていたが、他の色分け対応チップと見た目がほぼ同じで
// 「クリックできるのに反応しない壊れたボタン」に見えていた。呼び出し側
// （下記rows.filter）で色分け対応軸だけに絞り込むよう変更したため、このコンポーネント
// 自体は非活性描画を持たず常にクリック可能な<button>のみを描画する。
// 改善計画: ルート設定タブの軸チップ（RouteSettingsPanel.tsx: renderLegendChip）と
// レイアウトを揃える（ユーザー指摘、2026-09-02）——(i)説明ポップオーバー・地図色分け
// アイコンを追加する。ただし後者の役割はRouteSettingsPanel側（layerVisibilityの
// ON/OFF、視界内の全道路を背景色分け）とは異なる。ルート確定後（page.tsx:
// showWindAxis = layerVisibility.windAxis && !hasDetail 等）は評価軸グループの背景
// 表示自体が無効化され、この「地図の色分け」チップ列（＝選択中ルートの線色分け）が
// 役割を引き継ぐ設計のため、独立した背景レイヤーのON/OFFを持たせると無効化された
// 背景表示と紛らわしい・実際には何も起きないボタンになる。ユーザー判断（2026-09-02、
// 「ルートに合わせて対応する色付けをしたい」）により、アイコンはトグルボタンと同じ
// onSelect（このチップを選択＝ルートをこの軸で色分け）を呼ぶ——レイアウトの見た目を
// 揃えつつ、実際の切り替えは常にルート線の色分けに一本化する。
function AxisChip({
  color,
  label,
  ariaLabel,
  pressed,
  onSelect,
  description,
}: {
  color: string;
  label: string;
  ariaLabel: string;
  pressed: boolean;
  onSelect: () => void;
  description?: string;
}) {
  return (
    <span className={legendStyles.legendChip}>
      <button type="button" className={styles.axisToggle} aria-pressed={pressed} aria-label={ariaLabel} onClick={onSelect}>
        <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: color }} />
        <span>{label}</span>
      </button>
      {description && (
        <Popover.Root>
          <Popover.Trigger asChild>
            <button type="button" className={legendStyles.legendInfoButton} aria-label={`${label}の説明を表示`}>
              <InfoIcon />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content className={legendStyles.legendInfoPopover} side="bottom" align="start" sideOffset={6}>
              {description}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      )}
      {description && (
        // aria-labelはトグルボタン（ariaLabel、「〜で地図を色分け」）と意図的に文言を
        // 変える——同一の名前だと2つのボタンがアクセシビリティツリー上・テストの
        // getByRole(name)双方で区別できなくなる（RouteSettingsPanel.module.cssの
        // legendMapColorButtonは元々「〜で地図を色分け表示」という別文言を使っており、
        // ここでも踏襲するだけで済む）。
        <button
          type="button"
          className={legendStyles.legendMapColorButton}
          aria-pressed={pressed}
          aria-label={`${label}で地図を色分け表示`}
          onClick={onSelect}
        >
          <MapAppearanceIcon size={13} />
        </button>
      )}
    </span>
  );
}

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
  // 改善計画T524（T518コードレビューP1指摘）: 以前はrows.length===0の場合にコンポーネント
  // 全体を空状態文言だけへ差し替えていたため、内訳データが無い候補を選ぶと「地図の色分け」
  // チップ列・凡例の表示設定ポップオーバー（総合難易度モードへ戻す唯一のUI導線を含む）まで
  // 道連れで消えていた。空状態の対象を内訳セクション（.breakdown）だけへ限定する。
  const rows = axes.filter((axis) => axisDifficulties[axis.axisId] != null);

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

      {/* 改善計画T545: 「総合難易度」単独行＋各軸チップが内訳の各行へ埋め込まれていた
          選択UIを、ルート設定タブの軸チップ列（chipRow、折り返して並ぶ）と同じ見た目・
          操作性の1行へ統合した（ユーザー実機指摘）。地図の色分け対象を選ぶ役割はこの
          チップ列だけが持ち、下の内訳（breakdown）は選択状態を持たない読み取り専用の
          一覧のまま残す（内訳だけを見て複数軸を横断比較する既存の使い方を変えない）。
          改善計画T545フォローアップ（ユーザー指摘「タブ内の地図の色分けが切り替えられない」）:
          routeStyleModesはsupports_route_coloring===trueの軸だけから生成される
          （car_stress・accident・night・bicycle_infra_quality等は対象外、routeStyleModes.ts
          参照）。以前はそうした軸も非活性チップとしてこの列に並べていたが、色分け対応チップと
          見分けにくく「壊れたボタン」に見えていた。ここで色分け対応軸だけへ絞り込むことで、
          この列に並ぶチップは常にクリック可能になる（評価はできても地図の色分けには
          対応しない軸の存在自体は、下の内訳一覧に引き続き表示されるため情報は失われない）。 */}
      <div className={`${legendStyles.chipRow} ${styles.selectorRow}`}>
        <AxisChip
          color={TOTAL_DOT_COLOR}
          label="総合難易度"
          ariaLabel="総合難易度で地図を色分け"
          pressed={isTotalSelected}
          onSelect={() => onRouteStyleModeChange("difficulty")}
        />
        {rows
          .filter((axis) => routeStyleModes.some((mode) => mode.id === axis.axisId))
          .map((axis) => (
            <AxisChip
              key={axis.axisId}
              color={axisColors[axis.axisId] ?? TOTAL_DOT_COLOR}
              label={axis.label}
              ariaLabel={`${axis.label}で地図を色分け`}
              pressed={routeStyleModeId === axis.axisId}
              onSelect={() => onRouteStyleModeChange(axis.axisId)}
              description={axis.description}
            />
          ))}
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

      <div className={styles.breakdown}>
        <p className={styles.hint}>内訳（重み付き寄与度）</p>
        {rows.length === 0 ? (
          <p className={styles.empty}>このルートで表示できる評価軸データがありません</p>
        ) : (
        <ul className={styles.list}>
          {rows.map((axis) => {
            const raw = axisDifficulties[axis.axisId];
            const value = contribution(axis.axisId);
            const axisColor = axisColors[axis.axisId] ?? TOTAL_DOT_COLOR;
            return (
              <li key={axis.axisId} className={styles.row}>
                <span className={styles.rowLabel}>
                  <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: axisColor }} />
                  <span>{axis.label}</span>
                </span>
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
        )}
      </div>
    </div>
  );
}
