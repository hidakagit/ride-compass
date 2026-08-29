"use client";

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
      {/* total_scoreは何点満点かや算出根拠が画面から分からなかったため、一覧の先頭に
          簡潔な説明を添える（backend/app/scoring.yamlの重み付けに対応。この一覧内の
          候補同士でのみ比較できる相対評価であり、他のリクエストの結果とは比較できない）。
          表示名は「総合スコア」から「おすすめ度」へ変更（T30）: ルート色分けの「総合難易度」と
          極性が逆（スコア=高いほど良い/難易度=高いほど悪い）なのに両方「総合」で紛らわしかった。
          改善計画T421: サマリ行は「距離」と「軸による重みづけ（おすすめ度=total_score、
          T401でdistance_weight+difficulty_weightの2指標へ単純化済み）」の2つへ単純化する
          確定仕様に合わせ、旧scoring.yaml時代の個別フィールド（獲得標高・風・舗装率）は
          撤去した（値自体は引き続きRouteCandidateに残るが、候補順位付け・このサマリ行の
          どちらからも参照しない）。軸ごとの内訳を見たい場合はレーダーチャート
          （区間クリック、T403）・ルート全体プロファイル（BottomSheet、T402）を使う。 */}
      <p className={styles.scoreHint}>{SCORE_HINT}</p>
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
