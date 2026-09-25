"use client";

import { Fragment } from "react";

import ErrorText from "@/components/ErrorText/ErrorText";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { NewRouteIcon, RouteDiffIcon, UndoAllIcon, UndoIcon } from "@/components/ui/icons/icons";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { formatDurationShort } from "@/features/route/formatDuration";
import type { RouteCandidate } from "@/types/route";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";

interface RouteSplicePanelProps {
  /** 編集の元。1本に固定で、地図で他候補を押しても変わらない。 */
  displayed: RouteCandidate;
  /** 適用済みの乗り換えの数。 */
  appliedCount: number;
  /** 次に選べる乗り換えがあるか（無ければ「他の候補と別の道を通る区間がありません」）。 */
  hasAlternatives: boolean;
  /** 直前の1手を戻す。 */
  onUndo: () => void;
  /** 乗り換えをすべて取り消して元のルートへ戻す。 */
  onReset: () => void;
  /** 「差分を見る」で評価した、いまの組み合わせの候補。まだ見ていなければnull。 */
  preview: RouteCandidate | null;
  /** 差分の評価を待っている間はtrue。 */
  previewing: boolean;
  /** いまの組み合わせを評価して結果を出す。 */
  onPreview: () => void;
  onApply: () => void;
  /** 合成した経路の評価を待っている間はtrue。 */
  applying: boolean;
  /** 合成に失敗した理由。押した場所から見えないと「押しても何も起きない」になる。 */
  error: string | null;
  /** 編集をやめて候補の一覧へ戻る。 */
  onCancel: () => void;
  /** 公開軸すべて（差分バーのラベルの正本）。 */
  axes: readonly PreferenceAxisDef[];
  /** 軸id→色（ルート設定パネルの軸チップと同じ色）。 */
  axisColors: Record<string, string>;
}

/** 寄与度の差がこれ未満の軸は差分バーへ出さない（1pxの破片が並ぶと読めない）。 */
const MIN_CONTRIBUTION_DELTA = 0.1;
/** 差分バーの下へ数値を書く軸の数。大きい順。 */
const LABELLED_DELTA_COUNT = 2;

/** 表示する桁で丸めた差。色を変えるかどうかも**この値**で決める——生の差で判断すると、
 * 画面には「±0」と出ているのに色だけ増減を主張する。 */
function roundToDigits(value: number, digits: number): number {
  return Number(value.toFixed(digits));
}

function digitsOf(label: string): number {
  return label === "距離" ? 1 : 0;
}

function formatDelta(value: number, digits: number): string {
  const rounded = roundToDigits(value, digits);
  if (rounded === 0) return "±0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}`;
}

/** 元→編集後で寄与度が動いた軸（大きい順）。減った軸は負、増えた軸は正。 */
function contributionDeltas(
  base: Record<string, number>,
  after: Record<string, number>,
  axes: readonly PreferenceAxisDef[],
): { axisId: string; label: string; delta: number }[] {
  return axes
    .map((axis) => ({
      axisId: axis.axisId,
      label: axis.label,
      delta: (after[axis.axisId] ?? 0) - (base[axis.axisId] ?? 0),
    }))
    .filter((item) => Math.abs(item.delta) >= MIN_CONTRIBUTION_DELTA)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}

export default function RouteSplicePanel({
  displayed,
  appliedCount,
  hasAlternatives,
  onUndo,
  onReset,
  preview,
  previewing,
  onPreview,
  onApply,
  applying,
  error,
  onCancel,
  axes,
  axisColors,
}: RouteSplicePanelProps) {
  // edge_idsを返さないエンジン・古い候補では区間を出せない（backendが空で返す）。
  // 区間の指定は「どの軸をどこへ渡すか」を取り違えても値としては通ってしまい、
  // **地図で光っている帯と実際に差し替わる区間がずれる**という形でしか現れない。
  const unavailable = displayed.edge_ids.length === 0;
  const busy = previewing || applying;
  const deltas = preview ? contributionDeltas(displayed.axis_contributions, preview.axis_contributions, axes) : [];
  const scale = deltas.reduce((max, item) => Math.max(max, Math.abs(item.delta)), 0);

  const duration = (seconds: number | null | undefined) => (seconds != null ? formatDurationShort(seconds) : null);
  const rounded = (value: number | null | undefined) => (value != null ? `${Math.round(value)}` : null);

  // 1セルに「元→編集後 差」を収める（列見出しを持たないぶん1行減る）。
  const metrics: { label: string; base: string | null; after: string | null; delta: number | null }[] = [
    {
      label: "距離",
      base: `${displayed.distance_km.toFixed(1)}`,
      after: preview ? `${preview.distance_km.toFixed(1)}km` : null,
      delta: preview ? preview.distance_km - displayed.distance_km : null,
    },
    {
      label: "所要",
      base: duration(displayed.estimated_duration_seconds),
      after: duration(preview?.estimated_duration_seconds),
      delta:
        preview?.estimated_duration_seconds != null && displayed.estimated_duration_seconds != null
          ? (preview.estimated_duration_seconds - displayed.estimated_duration_seconds) / 60
          : null,
    },
    {
      label: "総合難易度",
      base: rounded(displayed.overall_difficulty),
      after: rounded(preview?.overall_difficulty),
      delta:
        preview?.overall_difficulty != null && displayed.overall_difficulty != null
          ? preview.overall_difficulty - displayed.overall_difficulty
          : null,
    },
    {
      label: "負荷",
      base: rounded(displayed.difficulty_load),
      after: rounded(preview?.difficulty_load),
      delta:
        preview?.difficulty_load != null && displayed.difficulty_load != null
          ? preview.difficulty_load - displayed.difficulty_load
          : null,
    },
  ];
  const halves = [metrics.slice(0, 2), metrics.slice(2)];

  return (
    <section
      className={cn(
        cardVariants({ variant: "outline" }),
        "flex flex-col gap-1.5 rounded-lg border-[var(--color-border)] bg-[var(--color-surface-2)]",
      )}
      aria-labelledby="splice-heading"
    >
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="bare"
          className="px-0.5 text-[15px]"
          aria-label="編集をやめて候補へ戻る"
          onClick={onCancel}
        >
          ‹
        </Button>
        <h3 className={cn(textVariants({ variant: "heading" }), "font-semibold")} id="splice-heading">
          区間の乗り換え
        </h3>
        {/* 使い方は画面へ書かずここへ置く（設計原則「冗長なものは削る」）。 */}
        <InfoPopover triggerAriaLabel="区間の乗り換えの説明">
          地図の破線が、いまの道から乗り換えられる先です。タップするとそこへ乗り換わり、その先に
          分かれ道があれば次の破線が出ます。太い線が、いま作っているルートです。軸の棒は中央が0で、左（−）へ
          伸びた軸ほど難易度が下がり、右（＋）へ伸びた軸ほど上がっています。
        </InfoPopover>
        {appliedCount > 0 && <span className={cn(textVariants({ variant: "hint" }), "ml-1")}>{appliedCount}回</span>}
        {!unavailable && (
          <div className="ml-auto flex items-center gap-1.5">
            {appliedCount > 0 && (
              <>
                <Button size="iconLabel" onClick={onUndo} disabled={busy}>
                  <UndoIcon size={18} />
                  1つ戻す
                </Button>
                <Button size="iconLabel" onClick={onReset} disabled={busy}>
                  <UndoAllIcon size={18} />
                  全部戻す
                </Button>
              </>
            )}
            <Button
              size="iconLabel"
              onClick={onPreview}
              disabled={appliedCount === 0 || busy}
              aria-busy={previewing}
              aria-label="差分を見る"
            >
              <RouteDiffIcon size={18} />
              差分
            </Button>
            <Button
              size="iconLabel"
              onClick={onApply}
              disabled={appliedCount === 0 || busy}
              aria-busy={applying}
              aria-label="新しいルートを作成"
              title="新しい候補として一覧へ加える"
            >
              <NewRouteIcon size={18} />
              作成
            </Button>
          </div>
        )}
      </div>

      {unavailable ? (
        <p className={textVariants({ variant: "hint" })}>この候補は経路のEdge情報を持たないため、区間を出せません。</p>
      ) : (
        <>
          {/* 指標はルート結果と同じ項目。2列×2行で、元→編集後の位置を縦に揃える。 */}
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[length:var(--font-size-md)]">
            {halves.map((half, index) => (
              // 5つの要素をこのgridの直接の子にする（行のラッパを挟むと列が行ごとに独立し、
              // 「所要」と「28分」のように縦位置が揃わない）。
              <dl
                className="m-0 grid grid-cols-[max-content_minmax(0,max-content)_max-content_minmax(0,max-content)_max-content] items-baseline gap-x-1 gap-y-0.5"
                key={index}
              >
                {half.map((metric) => {
                  const shown = metric.delta != null ? roundToDigits(metric.delta, digitsOf(metric.label)) : null;
                  return (
                    <Fragment key={metric.label}>
                      <dt className={textVariants({ variant: "note" })}>{metric.label}</dt>
                      <dd className="m-0 text-right text-[var(--color-muted)]">{metric.base ?? "—"}</dd>
                      {/* 評価前は矢印も出さない（行き先が無いのに→だけ残ると読み手が待たされる）。 */}
                      <dd className={cn(textVariants({ variant: "note" }), "m-0")} aria-hidden="true">
                        {metric.after ? "→" : ""}
                      </dd>
                      <dd
                        className="m-0 font-bold data-[better=true]:text-[var(--color-accent)] data-[worse=true]:text-[var(--color-route-splice)]"
                        data-worse={shown != null && shown > 0}
                        data-better={shown != null && shown < 0}
                      >
                        {metric.after ?? ""}
                      </dd>
                      <dd
                        className="m-0 text-[length:var(--font-size-xs)] data-[better=true]:text-[var(--color-accent)] data-[worse=true]:text-[var(--color-route-splice)]"
                        data-worse={shown != null && shown > 0}
                        data-better={shown != null && shown < 0}
                      >
                        {metric.delta != null ? formatDelta(metric.delta, digitsOf(metric.label)) : ""}
                      </dd>
                    </Fragment>
                  );
                })}
              </dl>
            ))}
          </div>

          {/* 軸別は元・編集後の2本を並べず、差だけの1本にする。中央が0で、左が楽になった側。 */}
          {deltas.length > 0 && (
            <div className="mt-0.5 flex items-center gap-1.5">
              <span className="text-[length:var(--font-size-sm)] leading-none font-bold text-[var(--color-accent)]">
                −
              </span>
              <div
                className="flex h-3 min-w-0 flex-1 items-stretch"
                role="img"
                aria-label={deltas.map((item) => `${item.label} ${formatDelta(item.delta, 1)}`).join("、")}
              >
                <div className="flex min-w-0 flex-[1_1_50%] justify-end">
                  {deltas
                    .filter((item) => item.delta < 0)
                    .map((item) => (
                      <span
                        key={item.axisId}
                        className="block h-full"
                        style={{
                          width: `${(Math.abs(item.delta) / scale) * 50}%`,
                          background: axisColors[item.axisId] ?? "var(--color-muted)",
                        }}
                      />
                    ))}
                </div>
                <div className="-my-0.5 w-0.5 bg-[var(--foreground)]" />
                <div className="flex min-w-0 flex-[1_1_50%] justify-start">
                  {deltas
                    .filter((item) => item.delta > 0)
                    .map((item) => (
                      <span
                        key={item.axisId}
                        className="block h-full"
                        style={{
                          width: `${(Math.abs(item.delta) / scale) * 50}%`,
                          background: axisColors[item.axisId] ?? "var(--color-muted)",
                        }}
                      />
                    ))}
                </div>
              </div>
              <span className="text-[length:var(--font-size-sm)] leading-none font-bold text-[var(--color-route-splice)]">
                ＋
              </span>
            </div>
          )}

          {error && <ErrorText>{error}</ErrorText>}

          <p className={textVariants({ variant: "hint" })}>
            {deltas.length > 0
              ? deltas.slice(0, LABELLED_DELTA_COUNT).map((item) => (
                  <span className="mr-2.5" key={item.axisId}>
                    {item.label} {formatDelta(item.delta, 1)}
                  </span>
                ))
              : appliedCount > 0
                ? "「差分」を押すと、乗り換えた結果が出ます"
                : hasAlternatives
                  ? "地図の破線をタップして乗り換えます"
                  : "他の候補と別の道を通る区間がありません。"}
          </p>
        </>
      )}
    </section>
  );
}
