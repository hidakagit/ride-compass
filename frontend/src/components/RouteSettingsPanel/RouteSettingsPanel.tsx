"use client";

import { useEffect, useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import LayerChip from "@/components/Map/LayerChip";
import Disclosure from "@/components/Disclosure/Disclosure";
import WindBearingSlider from "@/components/WindBearingSlider/WindBearingSlider";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { FieldLabel, withAutoEnable } from "@/components/Map/recipeControls";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { isDedicatedWayValueLayerId, type MapLayerId, type MapLayerVisibility } from "@/components/Map/mapLayers";
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
// ユーザー指摘（2026-08-31、「帯ごとに色を変えるのはできる？」）: 上記の固定7色パレットを
// index % 7で循環させていたため、軸が7件を超える（既定でも8件）と8件目以降の帯が既に
// 使われた色と衝突していた（軸スタジオが軸数を増やせる設計である以上、固定の色数上限を
// 持つこと自体が破綻の元）。HSL色相環を実際の軸数で等分して割り当てる方式へ変更し、
// 軸数がいくつであっても衝突しないようにする。indexは常にcatalog.axesの表示順
// （フルリスト内の位置）を使う——チェックを外した軸があっても、他の軸の色は動かない
// （表示順が変わらない限り、ある軸の色は常に同じという安定性を保つ）。
function stackBarColorForIndex(index: number, axisCount: number): string {
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
  /** ユーザー指摘（2026-08-31、モバイルでBottomSheet展開中は地図上のコンパススライダーが
   * 隠れて実質操作できない）を受け、評価軸としての風・勾配（windAxis/gradientAxis）向けの
   * 向き指定コンパスを地図上からこのパネル内（該当軸の重み詳細ポップオーバーの中、
   * renderBearingControl参照）へ移設した。「環境」グループ（windVector/gradientFill）向けの
   * コンパスは、MapOverlayControls経由の起動でBottomSheetを開く必要が無いため、引き続き
   * 地図上に残る（page.tsx参照）。値（windBearingDeg/gradientBearingDeg）はどちらの
   * コンパスも同じ状態を共有する。 */
  windBearingDeg: number;
  onWindBearingDegChange: (bearingDeg: number) => void;
  gradientBearingDeg: number;
  onGradientBearingDegChange: (bearingDeg: number) => void;
}

// 改善計画: 向き（bearing）を必要とする軸のaxis_id→対応する状態・setterの対訳。
// dedicated_way_value_layer=trueの軸は現状すべて向きが必須（backend/app/domain/
// dynamic_way_values.pyのneeds_bearing、wind/gradientとも常にtrue）だが、この値自体は
// backend内部専用でaxis-catalogには出てこない（改善計画T458）ため、フロント側は
// 既存のwindBearingDeg/gradientBearingDegという2つの独立したstate（page.tsx、T483で
// 汎用化を検討中の既知の技術的負債）にaxis_idで対応付けるほかない。3件目の対象軸が
// 増える場合はこの対訳表への追加に加え、page.tsx側のstate追加も必要になる。
function bearingControlFor(
  axisId: string,
  windBearingDeg: number,
  onWindBearingDegChange: (bearingDeg: number) => void,
  gradientBearingDeg: number,
  onGradientBearingDegChange: (bearingDeg: number) => void
): { value: number; onChange: (bearingDeg: number) => void } | undefined {
  if (axisId === "wind") return { value: windBearingDeg, onChange: onWindBearingDegChange };
  if (axisId === "gradient") return { value: gradientBearingDeg, onChange: onGradientBearingDegChange };
  return undefined;
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
  windBearingDeg,
  onWindBearingDegChange,
  gradientBearingDeg,
  onGradientBearingDegChange,
}: RouteSettingsPanelProps) {
  const catalog = useAxisCatalog();
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

  // 改善計画T418/T440: 軸id→地図表示レイヤーIDの解決。専用の表示レイヤーを持つ軸
  // （kind="ramp"、catalog.secondaryAxesのlayerId）はそのままレイヤーIDを返す。
  // 専用のway_id→値配信レイヤー（Redis経由、風・勾配が該当）を持つ軸は、axis_idの
  // ハードコード比較ではなく軸データ（axis.dedicatedWayValueLayer、domain/
  // axis_definitions.py: AxisDefinition.dedicated_way_value_layer参照）で判定する。
  // レイヤーIDは命名規約（`${axisId}Axis`、windAxis/gradientAxisの実例）から機械的に
  // 導出し、実際に配線済みのMapLayerIdであることを型ガードで確認する。どちらにも該当
  // しない軸はundefined（地図表示非対応）。
  function mapColorLayerIdFor(axisId: string): MapLayerId | undefined {
    const secondaryLayerId = catalog.secondaryAxes.find((a) => a.axisId === axisId)?.layerId;
    if (secondaryLayerId) return secondaryLayerId;
    const axis = catalog.axes.find((a) => a.axisId === axisId);
    if (!axis?.dedicatedWayValueLayer) return undefined;
    const candidateLayerId = `${axisId}Axis`;
    return isDedicatedWayValueLayerId(candidateLayerId) ? candidateLayerId : undefined;
  }

  // 改善計画T418: 軸1件ぶんの「地図で色分け」トグル。専用レイヤーが無い軸・ルート確定後の
  // 風・勾配はどちらも押せない案内表示にする（上記hasDetailのコメント参照）。トグル自体は
  // 既存のramp軸描画ロジック（axisVisibility、MapView.tsx）・windAxis/gradientAxis配信層
  // （useDynamicWayValues）をそのまま流用し、layerVisibility[layerId]のON/OFFを
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
    if (isDedicatedWayValueLayerId(layerId) && hasDetail) {
      return (
        <span className={styles.mapColorUnavailable} title={`ルート確定後は「生成したルートの色分け」の「${axis.label}」で確認できます`}>
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

  // ユーザー指摘（2026-08-31、モバイルでBottomSheet展開中は地図上のコンパススライダーが
  // 隠れて実質操作できない）: 評価軸としての風・勾配（windAxis/gradientAxis、上の
  // renderMapColorToggleの「色分け」トグルで起動する方）向けの向き指定コンパスを、
  // トグルがONの間だけ重み詳細ポップオーバー（下のrenderWeightDetailPopover参照）の中に
  // 表示する。トグルOFF中・非対象軸ではpopoverの中身に一切現れない。
  function renderBearingControl(axis: PreferenceAxisDef) {
    if (hasDetail) return null;
    const layerId = mapColorLayerIdFor(axis.axisId);
    if (!layerId || !isDedicatedWayValueLayerId(layerId) || !(layerVisibility[layerId] ?? false)) return null;
    const bearing = bearingControlFor(
      axis.axisId,
      windBearingDeg,
      onWindBearingDegChange,
      gradientBearingDeg,
      onGradientBearingDegChange
    );
    if (!bearing) return null;
    return (
      <div className={styles.bearingRow}>
        <span className={styles.bearingLabel}>{axis.label}の走行方位</span>
        <WindBearingSlider
          value={bearing.value}
          onChange={bearing.onChange}
          ariaLabel={`${axis.label}の走行方位`}
        />
      </div>
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

  function handleWeightChange(axisId: string, value: number) {
    setLastWeights((prev) => ({ ...prev, [axisId]: value }));
    handlePreferenceChange({ ...routePreference, [axisId]: value });
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
  // 細かい数値調整（0.01刻みでの単独設定・0への変更＝実質チェックOFF相当）は従来の
  // 詳細ポップオーバー（renderWeightDetailPopover）を引き続き使う。
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
    const handleWindowPointerMove = (moveEvent: PointerEvent) => {
      const drag = boundaryDragRef.current;
      if (!drag) return;
      const rawDelta = (moveEvent.clientX - drag.startClientX) / drag.pixelsPerUnit;
      const { weightA, weightB } = clampBoundaryDrag(drag.startWeightA, drag.startWeightB, rawDelta);
      handlePairWeightChange(drag.axisIdA, weightA, drag.axisIdB, weightB);
    };
    const handleWindowPointerUp = () => {
      boundaryDragRef.current = null;
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
        <p className={styles.sectionLabel}>重み配分[帯の境界をドラッグして配分を調整できます]</p>
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
            let cumulativePct = 0;
            return visible.slice(0, -1).map(({ axis: left, weight: leftWeight }, i) => {
              cumulativePct += (leftWeight / total) * 100;
              const right = visible[i + 1];
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
                />
              );
            });
          })()}
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
              <span className={styles.checkboxCell}>
                <Checkbox
                  checked={checked}
                  onCheckedChange={(next) => handleToggle(axis.axisId, next)}
                  aria-label={axis.label}
                />
              </span>
              <span className={styles.rowLabel}>
                <FieldLabel label={axis.label} description={axis.description} />
              </span>
              {/* ユーザー指摘（2026-08-31、「重み配分、スライドバーじゃなくてもう少し
                  スマートに各要素設定できない？やっぱりスクロールが気になる」「スクロールが
                  しにくくなった。コンパス部分のエリアはすべてコンパスが移動してしまう」）:
                  重みスライダー・向きコンパス（いずれもドラッグ操作でtouch-action:none相当の
                  領域を持つ）を常時表示のリスト行から追い出し、タップで開くRadix Popover
                  （Portalでdocument.body直下へ描画、FieldLabelの説明ポップオーバーと同じ
                  パターン）の中へ格納した。通常時のリストは「チェックボックス・ラベル・
                  現在値・色分けチップ」だけの1行になり、ドラッグ系UIが常設されないため
                  リストのスクロールを妨げない。 */}
              <Popover.Root>
                <Popover.Trigger asChild>
                  <button
                    type="button"
                    className={styles.weightValueTrigger}
                    aria-label={`${axis.label}の重みを詳細設定[現在${weight.toFixed(2)}]`}
                  >
                    {weight.toFixed(2)}
                  </button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content className={styles.weightDetailPopover} side="bottom" align="end" sideOffset={6}>
                    <input
                      type="range"
                      min="0"
                      max="0.6"
                      step="0.01"
                      value={weight}
                      disabled={!checked}
                      aria-label={`${axis.label}の重み`}
                      onChange={(e) => handleWeightChange(axis.axisId, Number(e.target.value))}
                      className={styles.detailSlider}
                    />
                    {renderBearingControl(axis)}
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>
              {renderMapColorToggle(axis)}
            </div>
          );
        })}
      </div>

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
