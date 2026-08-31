"use client";

import { FieldLabel } from "@/components/Map/recipeControls";
import { SCORING_AXES } from "@/lib/evaluationAxes";
import type { RouteCandidate } from "@/types/route";
import styles from "./RouteList.module.css";

interface RouteListProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  onSelect: (id: string) => void;
}

// 評価軸カタログ（lib/evaluationAxes.ts）から生成する（改善計画T25）。軸を増やしても
// このファイルを直接編集する必要が無い。改善計画T421: ラベルのみの列挙（「距離の合わせ込み・
// 総合難易度を重み付けして算出」）だと、後者の「総合難易度」が何を合成した値かが伝わらず、
// ルート色分けモードの「総合難易度」（区間ごとの絶対基準スコア、routeStyleModes.ts）と
// 同名で紛らわしいという実機指摘を受け、各軸のdescription（軸スタジオの重みで合成した値
// であることを説明する文言）を併記する形へ見直した。
const SCORE_HINT = `おすすめ度は${SCORING_AXES.map((axis) => `${axis.label}（${axis.description}）`).join("・")}を重み付けして算出[この一覧内での相対評価]`;

// 改善計画T364/T365: 8方位以外の単一経路（経由地ルート・目的地ルート）のid集合。
const NON_DIRECTIONAL_ROUTE_IDS = new Set(["route-waypoints", "route-destination"]);

export default function RouteList({ routes, selectedRouteId, onSelect }: RouteListProps) {
  if (routes.length === 0) return null;

  return (
    <>
      {/* total_scoreは何点満点かや算出根拠が画面から分からなかったため、説明を用意している
          （backend/app/scoring.yamlの重み付けに対応。この一覧内の候補同士でのみ比較できる
          相対評価であり、他のリクエストの結果とは比較できない）。表示名は「総合スコア」から
          「おすすめ度」へ変更（T30）: ルート色分けの「総合難易度」と極性が逆
          （スコア=高いほど良い/難易度=高いほど悪い）なのに両方「総合」で紛らわしかった。
          ユーザー指示（省スペース化）: 常時表示の説明文だと縦幅を取るため、情報アイコンの
          ポップオーバー（FieldLabel、他パネルの軸説明と同じ部品）へ収納する。 */}
      <span className={styles.scoreHintTrigger}>
        <FieldLabel label="おすすめ度について" description={SCORE_HINT} />
      </span>
      <ul className={styles.list}>
        {routes.map((route) => {
          const selected = route.id === selectedRouteId;
          return (
            <li key={route.id}>
              <button
                type="button"
                onClick={() => onSelect(route.id)}
                className={selected ? `${styles.item} ${styles.itemSelected}` : styles.item}
              >
                {route.total_score != null && (
                  <strong>おすすめ度 {Math.round(route.total_score)}点 / </strong>
                )}
                {/* 改善計画T364/T365: 経由地ルート(route-waypoints)・目的地ルート
                    (route-destination)は候補が常に1件で「方位」という概念が無いため、
                    direction_label（固定文言、route_generator.py参照）をそのまま表示し
                    「〜方向」は付けない。 */}
                {NON_DIRECTIONAL_ROUTE_IDS.has(route.id) ? route.direction_label : `${route.direction_label}方向`}{" "}
                — {route.distance_km.toFixed(1)} km
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}
