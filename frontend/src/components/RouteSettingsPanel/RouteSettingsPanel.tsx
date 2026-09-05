"use client";

import { useEffect, useRef, useState } from "react";
import LayerChip from "@/components/Map/LayerChip";
import InfoPopover from "@/components/Map/InfoPopover";
import Disclosure from "@/components/Disclosure/Disclosure";
import { withAutoEnable } from "@/components/Map/recipeControls";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { HardFilterOverride, RoutePreferenceWeights } from "@/types/route";
import styles from "./RouteSettingsPanel.module.css";

// 一般ユーザー向けルート設定画面（改善計画T267、目論見書4章「①一般ユーザ向け
// ルーティング設定」）。常に表示されるメインの操作面に置く。重み配分バー
// （帯グラフ、ドラッグで調整）→軸の凡例チップ（有効/無効・説明文・地図色分け）→
// 除外する道路、という並び。
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
// ユーザー指摘（2026-08-31、「帯ごとに色を変えるのはできる？」）: 上記の固定7色パレットを
// index % 7で循環させていたため、軸が7件を超える（既定でも8件）と8件目以降の帯が既に
// 使われた色と衝突していた（軸スタジオが軸数を増やせる設計である以上、固定の色数上限を
// 持つこと自体が破綻の元）。HSL色相環を実際の軸数で等分して割り当てる方式へ変更し、
// 軸数がいくつであっても衝突しないようにする。indexは常にcatalog.axesの表示順
// （フルリスト内の位置）を使う——チェックを外した軸があっても、他の軸の色は動かない
// （表示順が変わらない限り、ある軸の色は常に同じという安定性を保つ）。
// 改善計画T518: RouteAxisProfile.tsx（ルート選択タブへ統合した軸チップ）が、同じ軸なら
// ここと同じ色ドットになるよう、この関数をそのまま再利用する（パネルをまたいでも同じ軸は
// 同じ色、という視覚的な一貫性のためexport）。
export function stackBarColorForIndex(index: number, axisCount: number): string {
  if (axisCount <= 0) return "#94a3b8";
  const hue = (index * (360 / axisCount)) % 360;
  return `hsl(${hue}, 62%, 55%)`;
}

function totalWeight(weights: RoutePreferenceWeights): number {
  return Object.values(weights).reduce((sum, w) => sum + (w > 0 ? w : 0), 0);
}

// 重み配分バー（帯グラフ）の境界ドラッグで動かせる重みの範囲。既存の詳細ポップオーバー内
// スライダー（min="0" max="0.6" step="0.01"）のmax/stepと揃える。下限は0ではなく
// WEIGHT_STEPにする——0まで下げるとその軸がチェックOFF相当（weight>0判定）に化け、
// ドラッグ中に帯の区間数が変わってしまうため、ドラッグでは「チェックを外す」操作を
// 兼ねさせない（0まで下げたい場合は詳細ポップオーバーかチェックボックス自体を使う）。
const WEIGHT_STEP = 0.01;
const STACK_BAR_MIN_WEIGHT = WEIGHT_STEP;
const STACK_BAR_MAX_WEIGHT = 0.6;

function roundToStep(value: number): number {
  return Number(value.toFixed(2));
}

/** 帯グラフの境界（隣り合う2軸の重み合計を変えずに一方から他方へ移す）ドラッグで、
 * 生の移動量（重み単位）を両軸の[STACK_BAR_MIN_WEIGHT, STACK_BAR_MAX_WEIGHT]範囲内へ
 * 収まるようクランプし、STEP単位へ丸めた最終的な2軸ぶんの新しい重みを返す。
 * 合計（weightA+weightB）は常に変わらない——丸め後もdeltaを共有するため浮動小数点誤差で
 * ずれない。 */
function clampBoundaryDrag(
  weightA: number,
  weightB: number,
  rawDelta: number
): { weightA: number; weightB: number } {
  const lowerBound = Math.max(STACK_BAR_MIN_WEIGHT - weightA, weightB - STACK_BAR_MAX_WEIGHT);
  const upperBound = Math.min(STACK_BAR_MAX_WEIGHT - weightA, weightB - STACK_BAR_MIN_WEIGHT);
  const clamped = Math.min(Math.max(rawDelta, lowerBound), upperBound);
  const steppedDelta = Math.round(clamped / WEIGHT_STEP) * WEIGHT_STEP;
  return {
    weightA: roundToStep(weightA + steppedDelta),
    weightB: roundToStep(weightB - steppedDelta),
  };
}

interface RouteSettingsPanelProps {
  hardFilters: HardFilterOverride;
  onHardFiltersChange: (next: HardFilterOverride) => void;
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
  hardFilters,
  onHardFiltersChange,
  routePreference,
  onRoutePreferenceChange,
  overrideEnabled,
  onOverrideEnabledChange,
}: RouteSettingsPanelProps) {
  const catalog = useAxisCatalog();
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

  // 各軸のチップは「色ドット+ラベル（タップで有効/無効切替）」「(i)説明文ポップオーバー」の
  // 2要素だけの1行。地図の色分け（レンズ）はこのパネルではなく地図上の凡例ピル（LensControl）
  // だけが持つ。重みの数値・スライダーはチップから完全に撤去し、重み配分
  // バー（帯グラフ）のドラッグ・矢印キー操作（T495）だけで調整する——1軸だけを狙って
  // 0.01刻みで細かく調整する手段は失うが、ユーザー判断で「帯グラフのみに一本化」を選択した。
  function renderLegendChip(axis: PreferenceAxisDef, index: number) {
    const weight = routePreference[axis.axisId] ?? 0;
    const checked = weight > 0;
    const color = stackBarColorForIndex(index, catalog.axes.length);
    return (
      <span key={axis.axisId} className={styles.legendChip} data-checked={checked}>
        <button
          type="button"
          className={styles.legendToggle}
          aria-pressed={checked}
          aria-label={checked ? `${axis.label}を無効にする` : `${axis.label}を有効にする`}
          onClick={() => handleToggle(axis.axisId, !checked)}
        >
          <span aria-hidden="true" className={styles.legendDot} style={{ background: color }} />
          <span className={styles.legendLabel}>{axis.label}</span>
        </button>
        <InfoPopover
          triggerClassName={styles.legendInfoButton}
          triggerAriaLabel={`${axis.label}の説明を表示`}
          contentClassName={styles.legendInfoPopover}
        >
          {axis.description}
        </InfoPopover>
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
  // 改善計画T471: 上記の初期値は「マウント時点のcatalog.defaultWeights」（軸カタログの
  // 実行時フェッチ完了前は静的フォールバック値）のスナップショットで固定されており、
  // フェッチ完了後にcatalog.defaultWeightsが実際の値へ更新されても、ユーザーがまだ
  // 触っていない軸のlastWeightsは古いフォールバック値のまま残り続けていた（チェックを
  // 一度外して戻すと、実際の既定重みではなく古い値へ復元される不具合）。
  // catalog.defaultWeightsが変わるたびに、「前回の既定値のまま変更されていない」軸だけを
  // 新しい既定値へ追従させる（handleWeightChangeで実際にユーザーが変更した値は保持する）。
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

  function handleToggle(axisId: string, checked: boolean) {
    const restored = checked ? lastWeights[axisId] || catalog.defaultWeights[axisId] || 0.1 : 0;
    handlePreferenceChange({ ...routePreference, [axisId]: restored });
  }

  // 帯グラフの境界ドラッグ用。隣り合う2軸ぶんを1回のstate更新へまとめる
  // （handleWeightChangeを2回呼ぶとReactのバッチングに乗っても中間状態が生まれうるため）。
  function handlePairWeightChange(axisIdA: string, valueA: number, axisIdB: string, valueB: number) {
    setLastWeights((prev) => ({ ...prev, [axisIdA]: valueA, [axisIdB]: valueB }));
    handlePreferenceChange({ ...routePreference, [axisIdA]: valueA, [axisIdB]: valueB });
  }

  const total = totalWeight(routePreference);

  // ユーザー要望（2026-08-31、「複数要素を足し合わせて1にするのを直感的に省スペース設定
  // できるUIはないか」）: 既存の重み配分バー（帯グラフ、以前は表示専用）を、隣り合う2要素の
  // 境界をドラッグして配分し直せるようにする。帯グラフはすでに「複数要素が合算されて全体に
  // なる」様子をひと目で示していたため、そこへ直接ドラッグ操作を足すのが最も直感的かつ
  // 省スペース（新規UI領域を追加しない）という判断（AskUserQuestionでユーザーが選択）。
  // 境界を1つ動かすと、その両隣の2軸間でだけ重みが移動する（他の軸・合計自体は変わらない）。
  // 続くユーザー要望（同日、「各軸毎の…スライドバーはなくしたい」）で、0.01刻みの
  // 単独重み調整ポップオーバー自体を廃止した——重みの調整手段はこの帯グラフのドラッグ・
  // 矢印キー操作のみになった（renderLegendChip参照）。
  const stackBarRef = useRef<HTMLDivElement>(null);
  // ドラッグ中の起点情報。境界ハンドルは16px幅しかなく、ドラッグ中にポインタが実際の
  // ハンドル要素の外へ出るのが常態のため、React要素スコープのonPointerMove（要素の外に
  // 出ると届かない）ではなくwindowへ直接pointermove/upを登録する（pointer captureは
  // 環境によって確実に効くとは限らないため使わない）。ハンドル自身の
  // onPointerDown（16px幅、touch-action:noneはこのハンドルだけに絞ってある——T493で
  // コンパスのtouch-action:noneが帯全体を覆っていた反省と同じ配慮）だけがReact要素側で、
  // 以降はwindow側のリスナーで完結する。
  const boundaryDragRef = useRef<{
    axisIdA: string;
    startWeightA: number;
    axisIdB: string;
    startWeightB: number;
    startClientX: number;
    pixelsPerUnit: number;
  } | null>(null);
  // ユーザー要望（2026-08-31、「バーをドラッグ中に数字が出てほしい」）: ドラッグ中の
  // 境界だけ、その両隣2軸の%を示すフロートバッジを出す（stackBarDragBadge参照）。
  // ドラッグ中かどうかの判定にしか使わないためrouteWeightsそのものではなくaxisIdの
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

  // 改善計画T419: 既定でON（除外）の3項目が常に展開表示でスペースを取りすぎるという
  // 実機フィードバックを受け、MapLayersPanel（.layerSection/.layerHeader/.chevron相当）と
  // 同じDisclosure折りたたみへ変更した。既定値のまま変えない利用者が大半と見込まれるため
  // 既定で閉じるが、既に既定値から変更済みの場合は「変更していることに気づかず開けない」
  // 事故を避けるため既定で開く（defaultOpenはuncontrolledのDisclosureの初期値としてのみ
  // 効く。以降の開閉はユーザー操作に委ねる）。
  const hardFilterCustomized = HARD_FILTER_CHIPS.some(({ key }) => (hardFilters[key] ?? true) !== true);

  return (
    <div className="flex flex-col gap-3">
      <div className={styles.stackBarWrap}>
        <div className={styles.stackBarHeader}>
          <p className={styles.sectionLabel}>重み配分[帯の境界をドラッグして配分を調整できます]</p>
          {/* ユーザー要望（2026-08-31、「情報アイコンを押すと、そのなかに凡例出してほしい」）:
              帯グラフの色と軸の対応を、見出し脇の情報アイコンから一覧できるようにする
              （凡例チップ側にも色ドットはあるが、折り返して並ぶため一覧性は弱い）。 */}
          <InfoPopover
            triggerClassName={styles.stackBarLegendTrigger}
            triggerAriaLabel="重み配分の凡例を表示"
            contentClassName={styles.legendInfoPopover}
          >
            <ul className={styles.stackBarLegendList}>
              {catalog.axes.map((axis, index) => {
                const weight = routePreference[axis.axisId] ?? 0;
                if (weight <= 0 || total <= 0) return null;
                const pct = Math.round((weight / total) * 100);
                return (
                  <li key={axis.axisId} className={styles.stackBarLegendItem}>
                    <span
                      aria-hidden="true"
                      className={styles.legendDot}
                      style={{ background: stackBarColorForIndex(index, catalog.axes.length) }}
                    />
                    <span className={styles.stackBarLegendLabel}>{axis.label}</span>
                    <span className={styles.stackBarLegendValue}>{pct}%</span>
                  </li>
                );
              })}
            </ul>
          </InfoPopover>
        </div>
        <div className={styles.stackBarOuter} ref={stackBarRef}>
          <div className={styles.stackBar}>
            {catalog.axes.map(({ axisId, label }, index) => {
              const weight = routePreference[axisId] ?? 0;
              if (weight <= 0 || total <= 0) return null;
              const pct = (weight / total) * 100;
              return (
                <div
                  key={axisId}
                  className={styles.stackSegment}
                  style={{ width: `${pct}%`, background: stackBarColorForIndex(index, catalog.axes.length) }}
                  title={`${label} ${Math.round(pct)}%`}
                />
              );
            })}
          </div>
          {(() => {
            const visible = catalog.axes
              .map((axis, index) => ({ axis, index, weight: routePreference[axis.axisId] ?? 0 }))
              .filter(({ weight }) => weight > 0 && total > 0);
            // 各区切りの累積%を先に純粋な配列として計算してから描画する（レンダー中に外側の
            // 変数を書き換えるとreact-hooks/immutability違反になるため、mapのコールバック内で
            // インデックスから逆算する）。
            const cumulativePcts = visible.reduce<number[]>((acc, { weight }) => {
              const previous = acc.at(-1) ?? 0;
              acc.push(previous + (weight / total) * 100);
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
                  {/* ユーザー要望（2026-08-31、「バーをドラッグ中に数字が出てほしい」）:
                      ドラッグ中だけ、両隣の%をフロートバッジで表示する（native title
                      ツールチップはホバー限定でモバイルでは事実上見えないため）。
                      改善計画: 数字だけでは境界の両側どちらの軸を指すか分からないという
                      指摘（2026-09-02）を受け、軸ラベルを併記した。ラベル併記で幅が
                      増えたため、バーの両端付近ではセンター寄せのままだとパネル外へ
                      はみ出す（同時に指摘・確認済み）。端寄せ（data-align）で回避する。 */}
                  {isDragging && (
                    <span
                      className={styles.stackBarDragBadge}
                      data-align={cumulativePct < 25 ? "start" : cumulativePct > 75 ? "end" : undefined}
                      aria-hidden="true"
                    >
                      {left.label} {Math.round((leftWeight / total) * 100)}% / {right.axis.label}{" "}
                      {Math.round((right.weight / total) * 100)}%
                    </span>
                  )}
                </div>
              );
            });
          })()}
        </div>
      </div>

      <div className={styles.legendRow}>{catalog.axes.map((axis, index) => renderLegendChip(axis, index))}</div>

      <Disclosure
        className={styles.hardFilters}
        triggerClassName={styles.hardFiltersTrigger}
        bodyClassName={styles.hardFiltersBody}
        defaultOpen={hardFilterCustomized}
        summary={
          <>
            <span aria-hidden="true" className={styles.hardFiltersChevron} />
            除外する道路
            {hardFilterCustomized && <span className={styles.hardFiltersBadge}>変更あり</span>}
          </>
        }
      >
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
      </Disclosure>

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
