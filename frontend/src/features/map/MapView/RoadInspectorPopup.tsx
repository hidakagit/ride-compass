"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import AxisDetail from "@/components/AxisContributionBar/AxisDetail";
import type { CatalogAxis } from "@/lib/catalogAxis";
import { isDebugEnabled } from "@/lib/debugLog";
import { getQueryClient } from "@/lib/queryClient";
import { fetchAxisInspector, type AxisInspectorConditions, type AxisInspectorResult } from "@/features/map/regionApi";
import type { RoutePreferenceWeights } from "@/types/route";
import { LANDCOVER_CLASSES } from "@/features/map/layers/landcoverClasses";
import { PRIMARY_ATTRIBUTE_LABELS } from "@/features/map/layers/primaryAttributes";
import { roadDisplayName, roadFactRows, roadFeatureKey, roadWayId, type RoadSurfacePopupProperties } from "./roadFacts";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { formatDifficulty } from "@/lib/mapDisplay/valueScale";

interface RoadInspectorPopupProps {
  properties: RoadSurfacePopupProperties;
  /** 公開軸すべて（順序・ラベルの正本）。ルート結果と同じ並びで内訳を出すために渡す。 */
  axes: readonly CatalogAxis[];
  /** 軸id→色（ルート結果の寄与度バー・凡例チップと同じ配色）。 */
  axisColors: Record<string, string>;
  /** 地図が今指定している走行の条件＋押した点のタイル。走る条件を使う軸は、この条件で値を求める。 */
  conditions: AxisInspectorConditions;
  /** 利用者がいま設定している重み（ルート生成へ送るのと同じもの）。nullなら既定の重み。 */
  routePreference: RoutePreferenceWeights | null;
}

// 地図の道をクリックしたときの中身。答えるのは「この道は何者で、なぜこの評価なのか」。
//
// **ルート結果と同じ部品・同じ配色で評価を出す**（`AxisContributionBar`・`AxisDetail`）——同じ「軸ごとの
// 効き方」を別の見た目で見せると、利用者は2つの読み方を覚えることになる。
// 評価は押したときだけ取りに行く（クリックのたびに引くとレート制限に当たる）。
// 開いたときに見せるのは名前と評価だけで、属性・土地被覆は畳む（地図の上の小さな枠に収めるため）。
export default function RoadInspectorPopup({
  properties,
  axes,
  axisColors,
  conditions,
  routePreference,
}: RoadInspectorPopupProps) {
  // 評価は道・走行の条件・重みごとに持つ。重みを変えたら、古い重みの評価を見せずに取り直しへ戻す。条件は押したときの
  // ものに留める——出発時刻は「今」へ5分刻みで進むので、今の条件で引き直すと開いている間に評価が消える。
  const weightsKey = JSON.stringify(routePreference);
  const conditionsKey = JSON.stringify(conditions);
  const [pressed, setPressed] = useState<{
    weightsKey: string;
    conditionsKey: string;
    conditions: AxisInspectorConditions;
  } | null>(null);
  const pinned = pressed !== null && pressed.weightsKey === weightsKey ? pressed : null;
  const name = roadDisplayName(properties);
  const wayId = roadWayId(properties);
  const featureKey = roadFeatureKey(properties);
  const inspector = useQuery(
    {
      queryKey: ["axis-inspector", wayId, featureKey, pinned?.conditionsKey ?? conditionsKey, weightsKey],
      queryFn: async () => {
        const value = await fetchAxisInspector(
          wayId!,
          featureKey,
          pinned !== null ? pinned.conditions : conditions,
          routePreference,
        );
        if (value === null) throw new Error("評価が返りませんでした");
        return value;
      },
      enabled: pinned !== null && wayId != null,
      // 同じ道を同じ条件・重みで開き直したときは、前に取った評価を出す（押すたびに引くとレート制限に当たる）。
      staleTime: Infinity,
    },
    getQueryClient(),
  );
  const result: AxisInspectorResult | null = inspector.data ?? null;

  const load = () => {
    if (pinned !== null) void inspector.refetch();
    else setPressed({ weightsKey, conditionsKey, conditions });
  };

  // 寄与度はbackendが返す（軸ごとの重み付き寄与、合計が合成スコアと一致する）。
  // フロントで重みを掛け直さない——ルート結果側と同じ規約。
  const contributions: Record<string, number> = {};
  for (const axis of result?.axes ?? []) {
    if (axis.contribution != null) contributions[axis.axis_id] = axis.contribution;
  }

  // 合成に使えた軸の重みの割合（%）。出すのと同じ丸めで100%に届かないときだけ、一部の軸だけの値だと添える。
  const coveredWeightPercent =
    result?.composite_difficulty != null ? Math.round(result.composite_difficulty.covered_weight_fraction * 100) : null;

  return (
    // 高さに上限を付け、あふれたら中でスクロールする——地図の上の枠は、中身が伸びても画面の外へ出てはいけない。
    <div className="max-h-[min(22rem,45vh)] max-w-68 overflow-y-auto text-[length:var(--font-size-md)] leading-[1.4]">
      {name !== null && <div className="mb-1 font-semibold">{name}</div>}
      {wayId != null && result === null && (
        <Button size="sm" className="disabled:cursor-progress" onClick={load} disabled={inspector.isFetching}>
          {inspector.isFetching ? "評価を取得中…" : "この道の評価を見る"}
        </Button>
      )}
      {inspector.isError && <p className={textVariants({ variant: "hint" })}>評価を取得できませんでした。</p>}
      {result !== null && (
        <div className="grid gap-1">
          {Object.keys(contributions).length > 0 ? (
            <AxisContributionBar
              axes={axes}
              contributions={contributions}
              axisColors={axisColors}
              renderDetail={(axis) => {
                const found = result.axes.find((a) => a.axis_id === axis.axisId);
                if (found === undefined || found.difficulty === null) return null;
                return <AxisDetail axis={axis} difficulty={found.difficulty} />;
              }}
            />
          ) : (
            <p className={textVariants({ variant: "hint" })}>この道で値を出せる評価軸がありません。</p>
          )}
          {result.composite_difficulty !== null && (
            <p className={cn(textVariants({ variant: "hint" }), "m-0")}>
              {`この道だけで見た難易度: ${formatDifficulty(result.composite_difficulty.value)}/100`}
              {coveredWeightPercent !== null && coveredWeightPercent < 100
                ? `[重みの約${coveredWeightPercent}%ぶんの評価軸だけ。残りの評価軸は、この道とこの走る条件では値が出せません]`
                : ""}
            </p>
          )}
        </div>
      )}
      <div className="mt-1 grid gap-0.5 border-t border-[var(--color-border)] pt-1">
        <RoadAttributeRows properties={properties} result={result} />
        {result !== null && <RoadLandcoverRows result={result} />}
      </div>
      {isDebugEnabled() && wayId != null && <p className={textVariants({ variant: "hint" })}>OSM way id: {wayId}</p>}
    </div>
  );
}

/** 「項目: 値」の行の並び。項目の名前は並びの中で重ならない。 */
function FactList({ rows }: { rows: readonly { label: string; value: string }[] }) {
  return (
    <dl className="m-0 grid gap-0.5">
      {rows.map((row) => (
        <div key={row.label} className="grid grid-cols-[5.5rem_1fr] gap-1.5">
          <dt className={cn(textVariants({ variant: "hint" }), "m-0")}>{row.label}</dt>
          <dd className="m-0 [overflow-wrap:anywhere]">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 道路の周囲100mリングの土地被覆。走行中に読むものではないため畳んでおき、閉じている
 * 間は最も多いクラスだけを見せる。クラスの割合は合計100%になるため、開いたときは割合の
 * 大きい順に並べ、0%のクラスは出さない。 */
function RoadLandcoverRows({ result }: { result: AxisInspectorResult }) {
  const landcover = result.landcover;
  if (landcover === null || landcover === undefined) return null;
  const rows = LANDCOVER_CLASSES.map((cls) => ({
    label: cls.label,
    value: landcover[cls.percentField as keyof typeof landcover] as number,
  }))
    .filter((row) => row.value >= 0.5)
    .sort((a, b) => b.value - a.value);
  if (rows.length === 0) return null;
  const top = rows[0];
  return (
    <details className="[&>summary]:cursor-pointer">
      <summary
        className={textVariants({ variant: "hint" })}
      >{`周囲の土地被覆: ${top.label} ${Math.round(top.value)}%`}</summary>
      <FactList rows={rows.map((row) => ({ label: row.label, value: `${Math.round(row.value)}%` }))} />
    </details>
  );
}

/** この道の属性。地図のタイルから分かる事実に、評価を取ったときに届くタグ（カタログに登録済みのもの）を足し、
 * **同じ項目は1度だけ**出す（タイルとタグの両方が持つ項目がある）。畳んでおく——走行中に読むものではなく、
 * 開いたままだと地図の上の枠からはみ出す。登録外の生タグ（`name`・`ref`等、OSM編集者が自由に書ける）は
 * 数が読めないため、さらに畳んで置く。 */
function RoadAttributeRows({
  properties,
  result,
}: {
  properties: RoadSurfacePopupProperties;
  result: AxisInspectorResult | null;
}) {
  const rows = [...roadFactRows(properties)];
  const others: { label: string; value: string }[] = [];
  const add = (label: string, value: string) => {
    if (!rows.some((row) => row.label === label)) rows.push({ label, value });
  };
  if (result !== null) {
    add(PRIMARY_ATTRIBUTE_LABELS.highway, result.highway);
    for (const [key, value] of Object.entries(result.tags)) {
      const label = PRIMARY_ATTRIBUTE_LABELS[key];
      if (label === undefined) others.push({ label: key, value });
      else add(label, value);
    }
  }
  return (
    <details className="[&>summary]:cursor-pointer">
      <summary className={textVariants({ variant: "hint" })}>この道の属性</summary>
      <FactList rows={rows} />
      {others.length > 0 && (
        <details className="[&>summary]:cursor-pointer">
          <summary className={textVariants({ variant: "hint" })}>その他のタグ</summary>
          <FactList rows={others} />
        </details>
      )}
    </details>
  );
}
