"use client";

import { useEffect, useRef, useState } from "react";
import InfoPopover from "@/components/Map/InfoPopover";
import { axisIconFor } from "@/components/Map/axisIconPalette";
import { withAutoEnable } from "@/components/Map/recipeControls";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import {
  SHARE_STEP_PCT,
  WEIGHT_STEP,
  adjustAxisShare,
  clampBoundaryDrag,
  totalWeight,
} from "@/lib/routeWeightShare";
import { retryAxisCatalogFetch, useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import styles from "./RouteSettingsPanel.module.css";

// 「ルート設定」区分の「重み」タブ。重み配分バー（帯グラフ、全軸の取り分が1本に収まる）→
// 選択中の軸の1行（名前・%・±）→軸チップ（有効な軸を先頭に%付きで並べ、チェックで
// 有効/無効、本体で調整対象を選ぶ）という並び。除外する道路は別タブ（HardFilterPanel）。
// 軸が増えても伸びるのはチップの領域だけで、そこは高さ上限と内部スクロールを持つ。
//
// 軸はカテゴリ（観測/推定/動的）で分けず、公開済みの軸を常にフラットな1本のリストとして
// 表示する（軸スタジオは常にcategory="推定"固定で軸を作るため）。軸の`category`データ
// 自体はbackend側にそのまま残す（他の用途のために消さない）。
//
// 軸の一覧・既定重みはuseAxisCatalog経由でGET /api/axis-catalogから取得する
// （is_published=Trueのみ）。軸スタジオがDBへ追加した軸も、コード変更・再デプロイなしに
// ここへ現れる（取得完了まで・失敗時は既存軸の静的フォールバックを使う）。

// 帯グラフの区間へ文字を入れられる最小の取り分（%）。狭い区間は文字が収まらないため、
// アイコン＋%→%のみ→何も出さない、の順に落とす（どの軸の%もチップ側では必ず読める）。
const SEGMENT_ICON_MIN_PCT = 10;
const SEGMENT_VALUE_MIN_PCT = 6;

// 重み配分バーの軸ごとの色分け。色自体に意味は持たせない識別用で、HSL色相環を実際の
// 軸数で等分して割り当てる（軸数がいくつであっても衝突しない）。indexは常に
// catalog.axesの表示順（フルリスト内の位置）を使う——チェックを外した軸があっても、
// 他の軸の色は動かない（表示順が変わらない限り、ある軸の色は常に同じという安定性を保つ）。
// RouteAxisProfile.tsx（ルート選択タブへ統合した軸チップ）が、同じ軸ならここと同じ
// 色ドットになるよう、この関数をそのまま再利用する（パネルをまたいでも同じ軸は同じ色、
// という視覚的な一貫性のためexport）。
export function stackBarColorForIndex(index: number, axisCount: number): string {
  if (axisCount <= 0) return "#94a3b8";
  const hue = (index * (360 / axisCount)) % 360;
  return `hsl(${hue}, 62%, 55%)`;
}

interface RouteSettingsPanelProps {
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (next: RoutePreferenceWeights) => void;
  /** route_preference上書きの有効フラグ（page.tsx参照）。既定値のまま操作しなければ
   * 無効のままでよく（DEFAULT_ROUTE_PREFERENCE＝backend既定値のため挙動は変わらない）、
   * 値を変えると自動でONになる（withAutoEnable）。一般ユーザーはこのフラグの存在自体を
   * 意識しない（トグルUIをこのパネルには出さない）。 */
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
}

export default function RouteSettingsPanel({
  routePreference,
  onRoutePreferenceChange,
  overrideEnabled,
  onOverrideEnabledChange,
}: RouteSettingsPanelProps) {
  const catalog = useAxisCatalog();
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

  // axisIconForはaxisIconPalette.tsxの固定辞書を引くだけの純関数だが、
  // react-hooks/static-componentsのeslintルールは`const X = fn(); <X/>`をコンポーネント
  // 本体直下で書くと「レンダー毎に新規生成している」と静的に誤検知する。ネストした関数の
  // 中では誤検知しないため、アイコンの描画はこの関数を通す（AxisComposer.tsxと同じ回避）。
  function AxisIcon({ axis, size = 14 }: { axis: PreferenceAxisDef; size?: number }) {
    const Icon = axisIconFor(axis.iconId);
    return <Icon size={size} />;
  }

  function renderAxisIcon(axis: PreferenceAxisDef, size: number, color: string) {
    return (
      <span aria-hidden="true" className={styles.legendIcon} style={{ color }}>
        <AxisIcon axis={axis} size={size} />
      </span>
    );
  }

  // カタログとroutePreferenceのキー集合を双方向に同期する。backendのroute_preference
  // 検証は「上書きするなら既知の全axis_idを明示する」方針（キー完全一致、
  // routers/routes.py: RoutePreferenceWeights._check_axis_keys）のため、どちら向きの
  // ズレを放置してもルート生成が422になる。
  // - 新しい軸（軸スタジオがDBへ追加した軸）が現れた場合: その既定重みを補う。
  // - 軸が消えた場合（公開軸のunpublish）: そのキーをroutePreferenceから削除する。
  //   これが無いと、unpublish直後に旧設定を保持したブラウザで次のルート生成が422で
  //   壊れる（docs/decisions/t221-axis-registry.md「Stage D拡張3」）。
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
  // 上記の初期値は「マウント時点のcatalog.defaultWeights」（軸カタログの実行時フェッチ
  // 完了前は静的フォールバック値）のスナップショットで固定される。フェッチ完了後に
  // catalog.defaultWeightsが実際の値へ更新されたら、「前回の既定値のまま変更されていない」
  // 軸だけを新しい既定値へ追従させる（ユーザーが手動で操作した値は保持する）——これが
  // 無いと、チェックを一度外して戻したときに実際の既定重みではなく古いフォールバック値へ
  // 復元されてしまう。
  const previousDefaultWeightsRef = useRef(catalog.defaultWeights);
  useEffect(() => {
    const previousDefaults = previousDefaultWeightsRef.current;
    previousDefaultWeightsRef.current = catalog.defaultWeights;
    if (previousDefaults === catalog.defaultWeights) return;
    setLastWeights((prev) => {
      const next = { ...prev };
      for (const [axisId, defaultWeight] of Object.entries(catalog.defaultWeights)) {
        if (!(axisId in prev) || prev[axisId] === previousDefaults[axisId]) {
          next[axisId] = defaultWeight;
        }
      }
      return next;
    });
  }, [catalog.defaultWeights]);

  // ±で調整する対象の軸。チェックを外された軸・カタログから消えた軸を指したままに
  // ならないよう、実際に出す軸は毎回「有効な軸の中から」引き直す。
  const [selectedAxisId, setSelectedAxisId] = useState<string | null>(null);

  function handleToggle(axisId: string, checked: boolean) {
    const restored = checked ? lastWeights[axisId] || catalog.defaultWeights[axisId] || 0.1 : 0;
    if (checked) setSelectedAxisId(axisId);
    handlePreferenceChange({ ...routePreference, [axisId]: restored });
  }

  // 帯グラフの境界ドラッグ用。隣り合う2軸ぶんを1回のstate更新へまとめる
  // （handleWeightChangeを2回呼ぶとReactのバッチングに乗っても中間状態が生まれうるため）。
  function handlePairWeightChange(axisIdA: string, valueA: number, axisIdB: string, valueB: number) {
    setLastWeights((prev) => ({ ...prev, [axisIdA]: valueA, [axisIdB]: valueB }));
    handlePreferenceChange({ ...routePreference, [axisIdA]: valueA, [axisIdB]: valueB });
  }

  // ±ボタン。増やしたぶんは他の有効な軸から按分して減る（adjustAxisShare）。
  // 動かせないとき（有効な軸が1つ・上下限に張り付き）はnullが返り、ボタン自体を押せなくする。
  function handleShareStep(axisId: string, deltaPct: number) {
    const next = adjustAxisShare(routePreference, axisId, deltaPct);
    if (!next) return;
    setLastWeights((prev) => {
      const merged = { ...prev };
      for (const [id, weight] of Object.entries(next)) {
        if (weight > 0) merged[id] = weight;
      }
      return merged;
    });
    handlePreferenceChange(next);
  }

  const total = totalWeight(routePreference);
  const sharePct = (weight: number) => (total > 0 ? (weight / total) * 100 : 0);

  // 有効な軸（重み>0）を先、無効な軸を後ろに並べる。有効な軸の%が先頭にまとまるため、
  // チップ領域をスクロールせずに「今どの軸が何%か」を読める。
  const axesWithIndex = catalog.axes.map((axis, index) => ({
    axis,
    index,
    weight: routePreference[axis.axisId] ?? 0,
  }));
  const enabledAxes = axesWithIndex.filter(({ weight }) => weight > 0);
  const orderedAxes = [...enabledAxes, ...axesWithIndex.filter(({ weight }) => weight <= 0)];
  const selected = enabledAxes.find(({ axis }) => axis.axisId === selectedAxisId) ?? enabledAxes[0] ?? null;
  const canIncrease = selected != null && adjustAxisShare(routePreference, selected.axis.axisId, SHARE_STEP_PCT) != null;
  const canDecrease = selected != null && adjustAxisShare(routePreference, selected.axis.axisId, -SHARE_STEP_PCT) != null;

  // 重み配分バー（帯グラフ）の隣り合う2要素の境界をドラッグして配分し直せる。
  // 境界を1つ動かすと、その両隣の2軸間でだけ重みが移動する（他の軸・合計自体は
  // 変わらない）。細かく2軸間で移したいときの手段で、1軸だけを増減する操作は
  // 選択中の軸の±（handleShareStep）が担う。
  const stackBarRef = useRef<HTMLDivElement>(null);
  // ドラッグ中の起点情報。境界ハンドルは16px幅しかなく、ドラッグ中にポインタが実際の
  // ハンドル要素の外へ出るのが常態のため、React要素スコープのonPointerMove（要素の外に
  // 出ると届かない）ではなくwindowへ直接pointermove/upを登録する（pointer captureは
  // 環境によって確実に効くとは限らないため使わない）。ハンドル自身の
  // onPointerDown（16px幅、touch-action:noneはこのハンドルだけに絞ってあり、帯全体は
  // 覆わない——スクロールジェスチャーを妨げないための配慮）だけがReact要素側で、
  // 以降はwindow側のリスナーで完結する。
  const boundaryDragRef = useRef<{
    axisIdA: string;
    startWeightA: number;
    axisIdB: string;
    startWeightB: number;
    startClientX: number;
    pixelsPerUnit: number;
  } | null>(null);
  // ドラッグ中の境界だけ、その両隣2軸の%を示すフロートバッジを出す
  // （stackBarDragBadge参照）。ドラッグ中かどうかの判定にしか使わないため
  // routeWeightsそのものではなくaxisIdの
  // ペアだけを持つ——実際のパーセント値はrender時にroutePreferenceから毎回計算する
  // （ドラッグ中はhandlePairWeightChange経由でroutePreferenceが更新されるたびに
  // 再レンダーされるため、この値は常に最新を指す）。
  const [draggingBoundary, setDraggingBoundary] = useState<{ axisIdA: string; axisIdB: string } | null>(null);

  function startBoundaryDrag(
    e: React.PointerEvent<HTMLDivElement>,
    axisIdA: string,
    startWeightA: number,
    axisIdB: string,
    startWeightB: number
  ) {
    const bar = stackBarRef.current;
    if (!bar || total <= 0) return;
    const barWidthPx = bar.getBoundingClientRect().width;
    if (barWidthPx <= 0) return;
    boundaryDragRef.current = {
      axisIdA,
      startWeightA,
      axisIdB,
      startWeightB,
      startClientX: e.clientX,
      pixelsPerUnit: barWidthPx / total,
    };
    setDraggingBoundary({ axisIdA, axisIdB });
    const handleWindowPointerMove = (moveEvent: PointerEvent) => {
      const drag = boundaryDragRef.current;
      if (!drag) return;
      const rawDelta = (moveEvent.clientX - drag.startClientX) / drag.pixelsPerUnit;
      const { weightA, weightB } = clampBoundaryDrag(drag.startWeightA, drag.startWeightB, rawDelta);
      handlePairWeightChange(drag.axisIdA, weightA, drag.axisIdB, weightB);
    };
    const handleWindowPointerUp = () => {
      boundaryDragRef.current = null;
      setDraggingBoundary(null);
      window.removeEventListener("pointermove", handleWindowPointerMove);
      window.removeEventListener("pointerup", handleWindowPointerUp);
      window.removeEventListener("pointercancel", handleWindowPointerUp);
    };
    window.addEventListener("pointermove", handleWindowPointerMove);
    window.addEventListener("pointerup", handleWindowPointerUp);
    window.addEventListener("pointercancel", handleWindowPointerUp);
  }

  // キーボード操作（矢印キーでWEIGHT_STEPずつ配分し直す）。ドラッグと同じclampBoundaryDrag
  // を使い、境界のrole="slider"としての最小限のアクセシビリティを確保する。
  function handleBoundaryKeyDown(
    e: React.KeyboardEvent<HTMLDivElement>,
    axisIdA: string,
    weightA: number,
    axisIdB: string,
    weightB: number
  ) {
    let rawDelta = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") rawDelta = -WEIGHT_STEP;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") rawDelta = WEIGHT_STEP;
    else return;
    e.preventDefault();
    const next = clampBoundaryDrag(weightA, weightB, rawDelta);
    if (next.weightA === weightA && next.weightB === weightB) return;
    handlePairWeightChange(axisIdA, next.weightA, axisIdB, next.weightB);
  }

  // 軸チップ1件。有効な軸は「チェック（有効/無効）」と「本体（±の対象に選ぶ）」の
  // 2つの押下領域を持ち、無効な軸は本体全体が「有効にする」だけを担う——無効な軸を
  // 選んでも動かす重みが無いため、押し分けられる領域を作らない。
  function renderLegendChip(axis: PreferenceAxisDef, index: number, weight: number) {
    const checked = weight > 0;
    const color = stackBarColorForIndex(index, catalog.axes.length);
    const isSelected = checked && selected?.axis.axisId === axis.axisId;
    const label = axis.chipLabel ?? axis.label;
    if (!checked) {
      return (
        <span key={axis.axisId} className={styles.legendChip} data-checked="false">
          <button
            type="button"
            className={styles.legendToggle}
            aria-pressed={false}
            aria-label={`${axis.label}を有効にする`}
            onClick={() => handleToggle(axis.axisId, true)}
          >
            <span aria-hidden="true" className={styles.legendIcon} style={{ color }}>
              <AxisIcon axis={axis} />
            </span>
            <span className={styles.legendLabel}>{label}</span>
          </button>
        </span>
      );
    }
    return (
      <span key={axis.axisId} className={styles.legendChip} data-checked="true" data-selected={isSelected}>
        <button
          type="button"
          className={styles.legendCheck}
          aria-pressed
          aria-label={`${axis.label}を無効にする`}
          onClick={() => handleToggle(axis.axisId, false)}
        >
          <span aria-hidden="true">✓</span>
        </button>
        <button
          type="button"
          className={styles.legendToggle}
          aria-pressed={isSelected}
          aria-label={`${axis.label}の配分を調整する`}
          onClick={() => setSelectedAxisId(axis.axisId)}
        >
          <span aria-hidden="true" className={styles.legendIcon} style={{ color }}>
            <AxisIcon axis={axis} />
          </span>
          {/* 略名は地図チップと同じ`chip_label`（最大4文字）。狭い幅で軸が折り返すぶんだけ
              縦を食うため、選ぶのに足りる長さへ詰める。押したときの説明・aria-labelは
              フルネームのまま。 */}
          <span className={styles.legendLabel}>{label}</span>
          <span className={styles.legendPct}>{Math.round(sharePct(weight))}%</span>
        </button>
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* 軸カタログを取得できていない間、重み配分は編集できるが送信時に省略され
          （page.tsx: handleGenerateの`axisCatalog.loaded`ガード）、backendの既定配分で
          探索される。黙って捨てると「重みを変えたのに結果が変わらない」を実験の差だと
          取り違えるため、何が起きるかと再試行導線を先に見せる。 */}
      {catalog.failed && (
        <p className={styles.catalogErrorNotice} role="status">
          <span>
            軸一覧を取得できませんでした。このまま生成すると重み配分は反映されず、
            サーバー既定の配分で探索します。
          </span>
          <button type="button" className={styles.catalogErrorRetry} onClick={retryAxisCatalogFetch}>
            再試行
          </button>
        </p>
      )}
      <div className={styles.stackBarWrap}>
        <div className={styles.stackBarHeader}>
          <p className={styles.sectionLabel}>重み配分</p>
          {/* 帯グラフの色と軸の対応を、見出し脇の情報アイコンから一覧できるようにする
              （チップの略名は4文字までのため、フルネームで確かめる先がここになる）。操作説明
              （帯の境界をドラッグして配分を調整できる旨）もここへ集約し、見出し自体は
              「重み配分」だけの短い表記にする。 */}
          <InfoPopover
            triggerClassName={styles.stackBarLegendTrigger}
            triggerAriaLabel="重み配分の凡例"
            contentClassName={styles.legendInfoPopover}
          >
            <p className={styles.stackBarLegendHint}>帯の境界をドラッグして配分を調整できます。</p>
            <ul className={styles.stackBarLegendList}>
              {enabledAxes.map(({ axis, index, weight }) => (
                <li key={axis.axisId} className={styles.stackBarLegendItem}>
                  <span
                    aria-hidden="true"
                    className={styles.legendDot}
                    style={{ background: stackBarColorForIndex(index, catalog.axes.length) }}
                  />
                  <span className={styles.stackBarLegendLabel}>{axis.label}</span>
                  <span className={styles.stackBarLegendValue}>{Math.round(sharePct(weight))}%</span>
                </li>
              ))}
            </ul>
          </InfoPopover>
          <span className={styles.stackBarTotal}>合計 100%</span>
        </div>
        <div className={styles.stackBarOuter} ref={stackBarRef}>
          <div className={styles.stackBar}>
            {enabledAxes.map(({ axis, index, weight }) => {
              const pct = sharePct(weight);
              return (
                <div
                  key={axis.axisId}
                  className={styles.stackSegment}
                  style={{ width: `${pct}%`, background: stackBarColorForIndex(index, catalog.axes.length) }}
                  title={`${axis.label} ${Math.round(pct)}%`}
                >
                  {pct >= SEGMENT_ICON_MIN_PCT && (
                    <span aria-hidden="true" className={styles.segmentIcon}>
                      <AxisIcon axis={axis} size={13} />
                    </span>
                  )}
                  {pct >= SEGMENT_VALUE_MIN_PCT && (
                    <span aria-hidden="true" className={styles.segmentValue}>
                      {Math.round(pct)}
                      {pct >= SEGMENT_ICON_MIN_PCT ? "%" : ""}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {(() => {
            const visible = enabledAxes;
            // 各区切りの累積%を先に純粋な配列として計算してから描画する（レンダー中に外側の
            // 変数を書き換えるとreact-hooks/immutability違反になるため、mapのコールバック内で
            // インデックスから逆算する）。
            const cumulativePcts = visible.reduce<number[]>((acc, { weight }) => {
              const previous = acc.at(-1) ?? 0;
              acc.push(previous + sharePct(weight));
              return acc;
            }, []);
            return visible.slice(0, -1).map(({ axis: left, weight: leftWeight }, i) => {
              const cumulativePct = cumulativePcts[i];
              const right = visible[i + 1];
              const isDragging =
                draggingBoundary?.axisIdA === left.axisId && draggingBoundary?.axisIdB === right.axis.axisId;
              return (
                <div
                  key={`boundary-${left.axisId}-${right.axis.axisId}`}
                  className={styles.stackBarHandle}
                  style={{ left: `${cumulativePct}%` }}
                  role="slider"
                  aria-label={`${left.label}と${right.axis.label}の配分`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(cumulativePct)}
                  tabIndex={0}
                  onPointerDown={(e) => startBoundaryDrag(e, left.axisId, leftWeight, right.axis.axisId, right.weight)}
                  onKeyDown={(e) => handleBoundaryKeyDown(e, left.axisId, leftWeight, right.axis.axisId, right.weight)}
                >
                  {/* ドラッグ中だけ、両隣の%と軸ラベルをフロートバッジで表示する
                      （native titleツールチップはホバー限定でモバイルでは事実上
                      見えないため）。ラベル併記で幅が増えるため、バーの両端付近では
                      センター寄せのままだとパネル外へはみ出す——端寄せ（data-align）で
                      回避する。 */}
                  {isDragging && (
                    <span
                      className={styles.stackBarDragBadge}
                      data-align={cumulativePct < 25 ? "start" : cumulativePct > 75 ? "end" : undefined}
                      aria-hidden="true"
                    >
                      {left.label} {Math.round(sharePct(leftWeight))}% / {right.axis.label}{" "}
                      {Math.round(sharePct(right.weight))}%
                    </span>
                  )}
                </div>
              );
            });
          })()}
        </div>
      </div>

      {/* 選択中の軸の1行。軸が何本あってもこの行の高さは変わらない。 */}
      {selected && (
        <div className={styles.selectedRow}>
          {renderAxisIcon(selected.axis, 16, stackBarColorForIndex(selected.index, catalog.axes.length))}
          <span className={styles.selectedName}>{selected.axis.label}</span>
          <InfoPopover
            triggerClassName={styles.stackBarLegendTrigger}
            triggerAriaLabel={`${selected.axis.label}の説明`}
            contentClassName={styles.legendInfoPopover}
          >
            {selected.axis.description}
          </InfoPopover>
          <span className={styles.selectedPct}>{Math.round(sharePct(selected.weight))}%</span>
          <span className={styles.shareStepper}>
            <button
              type="button"
              className={styles.shareStepButton}
              disabled={!canDecrease}
              aria-label={`${selected.axis.label}の配分を減らす`}
              onClick={() => handleShareStep(selected.axis.axisId, -SHARE_STEP_PCT)}
            >
              −
            </button>
            <button
              type="button"
              className={styles.shareStepButton}
              disabled={!canIncrease}
              aria-label={`${selected.axis.label}の配分を増やす`}
              onClick={() => handleShareStep(selected.axis.axisId, SHARE_STEP_PCT)}
            >
              ＋
            </button>
          </span>
        </div>
      )}
      <p className={styles.selectedHint}>
        増やしたぶんは、他の有効な軸から配分の大きい順に減ります（合計は常に100%）。
      </p>

      <div className={styles.legendRow}>
        {orderedAxes.map(({ axis, index, weight }) => renderLegendChip(axis, index, weight))}
      </div>

      <button
        type="button"
        className={styles.resetButton}
        onClick={() => {
          setLastWeights({ ...catalog.defaultWeights });
          handlePreferenceChange(catalog.defaultWeights);
        }}
      >
        重みを既定値に戻す
      </button>
    </div>
  );
}
