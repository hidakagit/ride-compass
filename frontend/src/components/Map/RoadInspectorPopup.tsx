"use client";

import { useState } from "react";
import AxisContributionBar from "@/components/RouteAxisProfile/AxisContributionBar";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { isDebugEnabled } from "@/lib/debugLog";
import { fetchAxisInspector } from "@/services/regionApi";
import type { AxisInspectorResult } from "@/types/traffic";
import { LANDCOVER_CLASSES } from "./landcoverClasses";
import { PRIMARY_ATTRIBUTE_LABELS } from "./primaryAttributes";
import { roadDisplayName, roadFactRows, type RoadSurfacePopupProperties } from "./roadFacts";
import styles from "./RoadInspectorPopup.module.css";

interface RoadInspectorPopupProps {
  properties: RoadSurfacePopupProperties;
  /** 公開軸すべて（順序・ラベルの正本）。ルート結果と同じ並びで内訳を出すために渡す。 */
  axes: readonly PreferenceAxisDef[];
  /** 軸id→色（ルート結果の寄与度バー・凡例チップと同じ配色）。 */
  axisColors: Record<string, string>;
}

// 地図の道をクリックしたときの中身。答えるのは「この道は何者で、なぜこの評価なのか」。
//
// **ルート結果と同じ部品・同じ配色で評価を出す**（`AxisContributionBar`）——同じ「軸ごとの
// 効き方」を別の見た目で見せると、利用者は2つの読み方を覚えることになる。
// 評価は押したときだけ取りに行く（クリックのたびに引くとレート制限に当たる）。
export default function RoadInspectorPopup({ properties, axes, axisColors }: RoadInspectorPopupProps) {
  const [result, setResult] = useState<AxisInspectorResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const name = roadDisplayName(properties);
  const facts = roadFactRows(properties);
  const wayId = properties.osm_way_id;

  const load = () => {
    if (wayId == null) return;
    setState("loading");
    fetchAxisInspector(wayId)
      .then((value) => {
        if (value === null) {
          setState("error");
          return;
        }
        setResult(value);
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
    <div className={styles.body}>
      {name !== null && <div className={styles.name}>{name}</div>}
      <dl className={styles.facts}>
        {facts.map((row) => (
          <div key={row.label} className={styles.factRow}>
            <dt className={styles.factLabel}>{row.label}</dt>
            <dd className={styles.factValue}>{row.value}</dd>
          </div>
        ))}
      </dl>
      {wayId != null && result === null && (
        <button type="button" className={styles.action} onClick={load} disabled={state === "loading"}>
          {state === "loading" ? "評価を取得中…" : "この道の評価を見る"}
        </button>
      )}
      {/* デバッグログONのときだけ道の識別子を出す。値がおかしい道を見つけたとき、
          地図で押した1本をそのままbackendの調査（scripts/measure_gradient_outliers.py
          --way）へ渡せるようにする。一般の利用者には読めない値のため常時は出さない。 */}
      {isDebugEnabled() && wayId != null && <p className={styles.note}>OSM way id: {wayId}</p>}
      {state === "error" && <p className={styles.note}>評価を取得できませんでした。</p>}
      {result !== null && (
        <div className={styles.result}>
          <RoadTagRows result={result} />
          <RoadLandcoverRows result={result} />
          <div className={styles.sectionLabel}>評価への効き方</div>
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
                    <span className={styles.detailHeading}>{axis.label}</span>
                    <span className={styles.detailValue}>{`軸別難易度 ${Math.round(found.difficulty)}/100`}</span>
                    <span className={styles.detailDescription}>{axis.description}</span>
                  </>
                );
              }}
            />
          ) : (
            <p className={styles.note}>この区間で算出できる軸がありません。</p>
          )}
          {result.composite_difficulty !== null && (
            <p className={styles.note}>
              {`この道だけで見た合成: ${result.composite_difficulty.toFixed(1)}/100`}
              {result.covered_weight_fraction !== null && result.covered_weight_fraction < 0.999
                ? `（重みの約${Math.round(result.covered_weight_fraction * 100)}%ぶんの軸だけ。勾配・風は進む向きが決まらないと出せません）`
                : ""}
            </p>
          )}
        </div>
      )}
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
    <details className={styles.others}>
      <summary className={styles.othersSummary}>{`周囲の土地被覆: ${top.label} ${Math.round(top.value)}%`}</summary>
      <dl className={styles.facts}>
        {rows.map((row) => (
          <div key={row.label} className={styles.factRow}>
            <dt className={styles.factLabel}>{row.label}</dt>
            <dd className={styles.factValue}>{`${Math.round(row.value)}%`}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/** 取得できたタグのうち、カタログに登録済みのものを「項目: 値」で出す。登録外の生タグ
 * （`name`・`ref`等、OSM編集者が自由に書ける）は畳んで置く——数が読めないため、開いた
 * ときだけ縦に伸びる形にする。 */
function RoadTagRows({ result }: { result: AxisInspectorResult }) {
  const known: [string, string][] = [];
  const others: [string, string][] = [];
  for (const [key, value] of Object.entries(result.tags)) {
    (PRIMARY_ATTRIBUTE_LABELS[key] !== undefined ? known : others).push([key, value]);
  }
  return (
    <>
      <div className={styles.sectionLabel}>この道の属性</div>
      <dl className={styles.facts}>
        <div className={styles.factRow}>
          <dt className={styles.factLabel}>{PRIMARY_ATTRIBUTE_LABELS.highway}</dt>
          <dd className={styles.factValue}>
            {result.highway ?? "不明"}
            {result.is_designated ? "（指定路線）" : ""}
          </dd>
        </div>
        {known.map(([key, value]) => (
          <div key={key} className={styles.factRow}>
            <dt className={styles.factLabel}>{PRIMARY_ATTRIBUTE_LABELS[key]}</dt>
            <dd className={styles.factValue}>{value}</dd>
          </div>
        ))}
      </dl>
      {others.length > 0 && (
        <details className={styles.others}>
          <summary className={styles.othersSummary}>その他のタグ</summary>
          <dl className={styles.facts}>
            {others.map(([key, value]) => (
              <div key={key} className={styles.factRow}>
                <dt className={styles.factLabel}>{key}</dt>
                <dd className={styles.factValue}>{value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </>
  );
}
