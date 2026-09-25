"use client";

import { useState } from "react";
import AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { isDebugEnabled } from "@/lib/debugLog";
import { fetchAxisInspector, type AxisInspectorConditions } from "@/services/regionApi";
import type { AxisInspectorResult } from "@/types/traffic";
import type { RoutePreferenceWeights } from "@/types/route";
import { LANDCOVER_CLASSES } from "@/features/map/layers/landcoverClasses";
import { PRIMARY_ATTRIBUTE_LABELS } from "@/features/map/layers/primaryAttributes";
import { roadDisplayName, roadFactRows, type RoadSurfacePopupProperties } from "./roadFacts";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface RoadInspectorPopupProps {
  properties: RoadSurfacePopupProperties;
  /** 公開軸すべて（順序・ラベルの正本）。ルート結果と同じ並びで内訳を出すために渡す。 */
  axes: readonly PreferenceAxisDef[];
  /** 軸id→色（ルート結果の寄与度バー・凡例チップと同じ配色）。 */
  axisColors: Record<string, string>;
  /** 地図が今指定している走行の条件＋押した点のタイル。**進行方向が決まらないと算出
   * できない軸（勾配・風）**は、これが無いと「データなし」になる。 */
  conditions?: AxisInspectorConditions | null;
  /** 利用者がいま設定している重み（ルート生成へ送るのと同じもの）。nullなら既定の重み。 */
  routePreference?: RoutePreferenceWeights | null;
}

// 地図の道をクリックしたときの中身。答えるのは「この道は何者で、なぜこの評価なのか」。
//
// **ルート結果と同じ部品・同じ配色で評価を出す**（`AxisContributionBar`）——同じ「軸ごとの
// 効き方」を別の見た目で見せると、利用者は2つの読み方を覚えることになる。
// 評価は押したときだけ取りに行く（クリックのたびに引くとレート制限に当たる）。
// 開いたときに見せるのは名前と評価だけで、属性・土地被覆は畳む（地図の上の小さな枠に収めるため）。
export default function RoadInspectorPopup({
  properties,
  axes,
  axisColors,
  conditions,
  routePreference = null,
}: RoadInspectorPopupProps) {
  // 取った評価は、取ったときの重みと一緒に持つ——重みを変えたら、古い重みの評価を見せずに取り直しへ戻す。
  const weightsKey = JSON.stringify(routePreference);
  const [loaded, setLoaded] = useState<{ weightsKey: string; result: AxisInspectorResult } | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const result = loaded !== null && loaded.weightsKey === weightsKey ? loaded.result : null;
  const name = roadDisplayName(properties);
  const wayId = properties.osm_way_id;

  const load = () => {
    if (wayId == null) return;
    setState("loading");
    const requestedKey = weightsKey;
    fetchAxisInspector(wayId, properties.feature_key, conditions, routePreference)
      .then((value) => {
        if (value === null) {
          setState("error");
          return;
        }
        setLoaded({ weightsKey: requestedKey, result: value });
        setState("idle");
      })
      .catch(() => setState("error"));
  };

  // 寄与度はbackendが返す（軸ごとの重み付き寄与、合計が合成スコアと一致する）。
  // フロントで重みを掛け直さない——ルート結果側と同じ規約。
  const contributions: Record<string, number> = {};
  for (const axis of result?.axes ?? []) {
    if (axis.contribution != null) contributions[axis.axis_id] = axis.contribution;
  }

  return (
    // 高さに上限を付け、あふれたら中でスクロールする——地図の上の枠は、中身が伸びても画面の外へ出てはいけない。
    <div className="max-h-[min(22rem,45vh)] max-w-68 overflow-y-auto text-[length:var(--font-size-md)] leading-[1.4]">
      {name !== null && <div className="mb-1 font-semibold">{name}</div>}
      {wayId != null && result === null && (
        <Button size="sm" className="disabled:cursor-progress" onClick={load} disabled={state === "loading"}>
          {state === "loading" ? "評価を取得中…" : "この道の評価を見る"}
        </Button>
      )}
      {state === "error" && <p className={textVariants({ variant: "hint" })}>評価を取得できませんでした。</p>}
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
                return (
                  <>
                    <span className="font-semibold">{axis.label}</span>
                    <span className="text-[length:var(--font-size-sm)]">{`軸別難易度 ${Math.round(found.difficulty)}/100`}</span>
                    <span className={textVariants({ variant: "hint" })}>{axis.description}</span>
                  </>
                );
              }}
            />
          ) : (
            <p className={textVariants({ variant: "hint" })}>この区間で算出できる軸がありません。</p>
          )}
          {result.composite_difficulty !== null && (
            <p className={cn(textVariants({ variant: "hint" }), "m-0")}>
              {`この道だけで見た合成: ${result.composite_difficulty.toFixed(1)}/100`}
              {result.covered_weight_fraction !== null && result.covered_weight_fraction < 0.999
                ? `（重みの約${Math.round(result.covered_weight_fraction * 100)}%ぶんの軸だけ。勾配・風は進む向きが決まらないと出せません）`
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
      <dl className="m-0 grid gap-0.5">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[5.5rem_1fr] gap-1.5">
            <dt className={cn(textVariants({ variant: "hint" }), "m-0")}>{row.label}</dt>
            <dd className="m-0 [overflow-wrap:anywhere]">{`${Math.round(row.value)}%`}</dd>
          </div>
        ))}
      </dl>
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
  const others: [string, string][] = [];
  const add = (label: string, value: string) => {
    if (!rows.some((row) => row.label === label)) rows.push({ label, value });
  };
  if (result !== null) {
    add(PRIMARY_ATTRIBUTE_LABELS.highway, result.highway ?? "不明");
    for (const [key, value] of Object.entries(result.tags)) {
      const label = PRIMARY_ATTRIBUTE_LABELS[key];
      if (label === undefined) others.push([key, value]);
      else add(label, value);
    }
  }
  return (
    <details className="[&>summary]:cursor-pointer">
      <summary className={textVariants({ variant: "hint" })}>この道の属性</summary>
      <dl className="m-0 grid gap-0.5">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[5.5rem_1fr] gap-1.5">
            <dt className={cn(textVariants({ variant: "hint" }), "m-0")}>{row.label}</dt>
            <dd className="m-0 [overflow-wrap:anywhere]">{row.value}</dd>
          </div>
        ))}
      </dl>
      {others.length > 0 && (
        <details className="[&>summary]:cursor-pointer">
          <summary className={textVariants({ variant: "hint" })}>その他のタグ</summary>
          <dl className="m-0 grid gap-0.5">
            {others.map(([key, value]) => (
              <div key={key} className="grid grid-cols-[5.5rem_1fr] gap-1.5">
                <dt className={cn(textVariants({ variant: "hint" }), "m-0")}>{key}</dt>
                <dd className="m-0 [overflow-wrap:anywhere]">{value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </details>
  );
}
