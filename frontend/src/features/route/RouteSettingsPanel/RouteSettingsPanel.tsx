"use client";

import { useEffect, useRef, useState } from "react";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { axisIconFor } from "@/lib/mapDisplay/axisIconPalette";
import { syncRoutePreferenceKeys } from "@/features/route/routePreferenceSync";
import { WEIGHT_STEP, clampBoundaryDrag, totalWeight } from "@/features/route/routeWeightShare";
import { retryAxisCatalogFetch, useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import { Button } from "@/components/ui/Button/Button";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { cn } from "@/lib/cn";
import { legendChipBodyClass, legendChipClass, legendIconClass } from "@/components/ui/AxisLegend/axisLegend";
import { calloutVariants } from "@/components/ui/Callout/Callout";

// overrideEnabledがfalseの間に値が変更されたら、変更自体は伝えつつ上書きも自動で有効化する
// ラッパー（凡例を操作したら自動でONにする、というパターン）。
function withAutoEnable<T>(
  overrideEnabled: boolean,
  onOverrideEnabledChange: (enabled: boolean) => void,
  setter: (next: T) => void,
): (next: T) => void {
  return (next) => {
    if (!overrideEnabled) onOverrideEnabledChange(true);
    setter(next);
  };
}

// 「ルート設定」区分の「重み」タブ。重み配分バー（帯グラフ、全軸の取り分が1本に収まり、
// 境界のドラッグで配分し直す）→軸チップ（有効な軸を先頭に%付きで並べ、タップで有効/無効、
// (i)で説明）という並び。帯そのものが配分と全体を示すため、見出しも合計の表記も持たない。
// 除外する道路は別タブ（HardFilterPanel）。
// 軸が増えても伸びるのはチップの領域だけで、そこは高さ上限と内部スクロールを持つ。
//
// 軸はカテゴリ（観測/推定/動的）で分けず、公開済みの軸を常にフラットな1本のリストとして
// 表示する（軸スタジオが新規に作る軸は常に"推定"のため、分けても大半が1つの群に寄る）。
// 軸の`category`データ自体はbackend側にそのまま残す（他の用途のために消さない）。
//
// 軸の一覧・既定重みはuseAxisCatalog経由でGET /api/axis-catalogから取得する
// （is_published=Trueのみ）。軸スタジオがDBへ追加した軸も、コード変更・再デプロイなしに
// ここへ現れる（届くまで・失敗したときは軸0件）。

// 帯グラフの区間へ文字を入れられる最小の取り分（%）。狭い区間は文字が収まらないため、
// アイコン＋%→%のみ→何も出さない、の順に落とす（どの軸の%もチップ側では必ず読める）。
const SEGMENT_ICON_MIN_PCT = 10;
const SEGMENT_VALUE_MIN_PCT = 6;

interface RouteSettingsPanelProps {
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (next: RoutePreferenceWeights) => void;
  /** route_preference上書きの有効フラグ（page.tsx参照）。既定値のまま操作しなければ
   * 無効のままでよく（既定値はカタログの`defaultWeights`＝backend既定値のため挙動は変わらない）、
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

  // カタログとroutePreferenceのキー集合を双方向に同期する。backendのroute_preference
  // 検証は「上書きするなら既知の全axis_idを明示する」方針（キー完全一致、
  // routers/routes.py: RoutePreferenceWeights._check_axis_keys）のため、どちら向きの
  // ズレを放置してもルート生成が422になる。
  // - 新しい軸（軸スタジオがDBへ追加した軸）が現れた場合: その既定重みを補う。
  // - 軸が消えた場合（公開軸のunpublish）: そのキーをroutePreferenceから削除する。
  //   これが無いと、unpublish直後に旧設定を保持したブラウザで次のルート生成が422で
  //   壊れる（docs/records/decisions/t221-axis-registry.md「Stage D拡張3」）。
  // どちらも値を変えずキーの追加/削除だけなのでoverrideEnabledは動かさない、
  // handlePreferenceChangeではなくonRoutePreferenceChangeを直接使う。
  useEffect(() => {
    // **取得が確定するまで同期しない。** 軸はDBが持ち、取得できるまでは0件である。
    // その状態で突き合わせると「公開軸が1つも無い」と読み、保存済みの重みを全部消す。
    if (!catalog.loaded) return;
    const synced = syncRoutePreferenceKeys(routePreference, catalog.defaultWeights);
    if (synced) onRoutePreferenceChange(synced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.defaultWeights, catalog.loaded]);

  // チェックを外した軸の重みを覚えておき、再度チェックしたときに元へ戻す
  // （routePreference自体は常に0を含む「実際に送る値」のため、ここでしか保持できない）。
  const [lastWeights, setLastWeights] = useState<Record<string, number>>(() => ({
    ...catalog.defaultWeights,
  }));
  // 上記の初期値は「マウント時点のcatalog.defaultWeights」（軸カタログが届く前は空）のスナップショットで固定される。フェッチ完了後に
  // catalog.defaultWeightsが実際の値へ更新されたら、「前回の既定値のまま変更されていない」
  // 軸だけを新しい既定値へ追従させる（ユーザーが手動で操作した値は保持する）——これが
  // 無いと、チェックを一度外して戻したときに実際の既定重みではなく届く前の値へ
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

  function handleToggle(axisId: string, checked: boolean) {
    const restored = checked ? lastWeights[axisId] || catalog.defaultWeights[axisId] || 0.1 : 0;
    handlePreferenceChange({ ...routePreference, [axisId]: restored });
  }

  // 帯グラフの境界ドラッグ用。隣り合う2軸ぶんを1回のstate更新へまとめる
  // （1軸ずつ`handlePreferenceChange`を2回呼ぶと、2回目も1回目を反映していない
  // `routePreference`から組み立てるため、1回目の変更が消える）。
  function handlePairWeightChange(axisIdA: string, valueA: number, axisIdB: string, valueB: number) {
    setLastWeights((prev) => ({ ...prev, [axisIdA]: valueA, [axisIdB]: valueB }));
    handlePreferenceChange({ ...routePreference, [axisIdA]: valueA, [axisIdB]: valueB });
  }

  const total = totalWeight(routePreference);
  // 有効な軸（重み>0）にだけ使うため、合計は必ず正。
  const sharePct = (weight: number) => (weight / total) * 100;

  // 有効な軸（重み>0）を先、無効な軸を後ろに並べる。有効な軸の%が先頭にまとまるため、
  // チップ領域をスクロールせずに「今どの軸が何%か」を読める。
  const axesWithWeight = catalog.axes.map((axis) => ({
    axis,
    weight: routePreference[axis.axisId] ?? 0,
  }));
  const enabledAxes = axesWithWeight.filter(({ weight }) => weight > 0);
  const orderedAxes = [...enabledAxes, ...axesWithWeight.filter(({ weight }) => weight <= 0)];

  // 重み配分バー（帯グラフ）の隣り合う2要素の境界をドラッグして配分し直せる。
  // 境界を1つ動かすと、その両隣の2軸間でだけ重みが移動する（他の軸・合計自体は
  // 変わらない）。
  const stackBarRef = useRef<HTMLDivElement>(null);
  // 境界ハンドルは16px幅しかなく、ドラッグ中にポインタがハンドル要素の外へ出るのが常態のため、
  // React要素スコープのonPointerMove（要素の外に出ると届かない）ではなくwindowへ直接
  // pointermove/upを登録する（pointer captureは環境によって確実に効くとは限らないため使わない）。
  // touch-action:noneはハンドルだけに絞り、帯全体のスクロールジェスチャーを妨げない。
  function startBoundaryDrag(
    e: React.PointerEvent<HTMLDivElement>,
    axisIdA: string,
    startWeightA: number,
    axisIdB: string,
    startWeightB: number,
  ) {
    const bar = stackBarRef.current;
    if (!bar) return;
    const barWidthPx = bar.getBoundingClientRect().width;
    if (barWidthPx <= 0) return;
    const startClientX = e.clientX;
    const pixelsPerUnit = barWidthPx / total;
    const handleWindowPointerMove = (moveEvent: PointerEvent) => {
      const rawDelta = (moveEvent.clientX - startClientX) / pixelsPerUnit;
      const { weightA, weightB } = clampBoundaryDrag(startWeightA, startWeightB, rawDelta);
      handlePairWeightChange(axisIdA, weightA, axisIdB, weightB);
    };
    const handleWindowPointerUp = () => {
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
    weightB: number,
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

  // 軸チップ1件。本体のタップで有効/無効を切り替え、(i)で軸の説明を読む。有効な軸には
  // 現在の%を併記する（帯の狭い区間には数字が入らないため、%を必ず読める場所がここ）。
  function renderLegendChip(axis: PreferenceAxisDef, weight: number) {
    const checked = weight > 0;
    const color = catalog.axisColors[axis.axisId];
    const label = axis.chipLabel ?? axis.label;
    return (
      <span key={axis.axisId} className={legendChipClass} data-checked={checked}>
        <Toggle
          variant="plain"
          className={cn(legendChipBodyClass, "cursor-pointer")}
          pressed={checked}
          aria-label={checked ? `${axis.label}を無効にする` : `${axis.label}を有効にする`}
          onClick={() => handleToggle(axis.axisId, !checked)}
        >
          <span aria-hidden="true" className={legendIconClass} style={{ color }}>
            <AxisIcon axis={axis} />
          </span>
          {/* 略名は地図チップと同じ`chip_label`（最大4文字）。狭い幅で軸が折り返すぶんだけ
              縦を食うため、選ぶのに足りる長さへ詰める。押したときの説明・aria-labelは
              フルネームのまま。 */}
          <span>{label}</span>
          {checked && (
            <span className="text-[length:var(--font-size-sm)] font-semibold tabular-nums">
              {Math.round(sharePct(weight))}%
            </span>
          )}
        </Toggle>
        <InfoPopover
          triggerClassName={"w-7 border-l border-[var(--color-border-muted)] max-mobile:w-6"}
          triggerAriaLabel={`${axis.label}の説明`}
        >
          {axis.description}
        </InfoPopover>
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* 軸カタログを取得できていない間、重み配分は編集できるが送信時に省略され
          （page.tsx: handleGenerateの`axisCatalog.loaded`ガード）、backendの既定配分で
          探索される。黙って捨てると「重みを変えたのに結果が変わらない」を実験の差だと
          取り違えるため、何が起きるかと再試行導線を先に見せる。
          **影響は重み配分だけではない**——同じ応答がタイル世代も運ぶため、地図の道路・POI・
          事故も出ない（世代の違う中身をブラウザのキャッシュへ残さないよう、届くまでソースを
          作らない）。地図側のチップにも理由を出すが、この再試行導線はここにしかない。 */}
      {catalog.failed && (
        <p
          className={cn(
            calloutVariants({ tone: "warning" }),
            "flex flex-wrap items-center gap-2 text-[length:var(--font-size-xs)]",
          )}
          role="status"
        >
          <span>
            {/* JSXは行の折り返しを半角スペース1つに畳む。日本語の文の途中では読点の直後に
                不自然な空きが出るため、文字列として繋ぐ。 */}
            {"軸一覧を取得できませんでした。地図の道路・POI・事故は表示できず、このまま生成すると" +
              "重み配分は反映されずサーバー既定の配分で探索します。"}
          </span>
          <Button variant="warning" size="xs" onClick={retryAxisCatalogFetch}>
            再試行
          </Button>
        </p>
      )}
      <div className="flex flex-col">
        <div className="relative" ref={stackBarRef}>
          <div className="flex h-7.5 gap-px overflow-hidden rounded-sm bg-[var(--color-surface-2)]">
            {enabledAxes.map(({ axis, weight }) => {
              const pct = sharePct(weight);
              return (
                <div
                  key={axis.axisId}
                  className="flex h-full min-w-0 flex-col items-center justify-center gap-px overflow-hidden"
                  style={{ width: `${pct}%`, background: catalog.axisColors[axis.axisId] }}
                  title={`${axis.label} ${Math.round(pct)}%`}
                >
                  {pct >= SEGMENT_ICON_MIN_PCT && (
                    <span aria-hidden="true" className="inline-flex text-[rgba(15,23,42,0.85)]">
                      <AxisIcon axis={axis} size={13} />
                    </span>
                  )}
                  {pct >= SEGMENT_VALUE_MIN_PCT && (
                    <span
                      aria-hidden="true"
                      className="text-[0.625rem] leading-none font-bold text-[rgba(15,23,42,0.85)] tabular-nums"
                    >
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
              return (
                <div
                  key={`boundary-${left.axisId}-${right.axis.axisId}`}
                  className="absolute -top-1.5 -bottom-1.5 flex w-4 -translate-x-1/2 cursor-col-resize touch-none items-center justify-center after:h-3.5 after:w-0.5 after:rounded-[1px] after:bg-[var(--color-surface)] after:shadow-[0_0_0_1px_var(--color-border-strong)] after:content-[''] hover:after:bg-[var(--color-accent)] hover:after:shadow-[0_0_0_1px_var(--color-accent)] focus-visible:outline-none focus-visible:after:bg-[var(--color-accent)] focus-visible:after:shadow-[0_0_0_1px_var(--color-accent)]"
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

      <div className="flex max-h-26 flex-wrap gap-2 overflow-y-auto">
        {orderedAxes.map(({ axis, weight }) => renderLegendChip(axis, weight))}
      </div>
    </div>
  );
}
