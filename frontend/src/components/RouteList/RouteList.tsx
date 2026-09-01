"use client";

import * as Tabs from "@radix-ui/react-tabs";
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

// 改善計画T545: 候補一覧は縦積みボタン（選ぶと同じ画面内の内訳が差し替わる）から、
// 候補ごとのタブへ再構成した（ユーザー実機指摘「ルート確認をもっとやりやすくしたい、
// ルートごとにタブを分けてほしい」）。タブ自体に「おすすめ度」を残すのは、切り替えずとも
// 候補間のおすすめ度を一覧比較できるようにするため（RouteAxisProfile側の表示は選択中の
// 1件だけなので、比較目的の一覧性はこのタブ列だけが持つ）。page.tsxの「ルート選択/比較」
// 外側タブと同じRadix Tabsだが、こちらはタブごとの中身（Tabs.Content）を持たない
// 純粋な選択UIのため、Tabs.List/Tabs.Triggerのみ使う（Tabs.Contentは省略可能、Radixの
// ロービングタブインデックス・ARIA付与はTriggerだけで機能する）。
export default function RouteList({ routes, selectedRouteId, onSelect }: RouteListProps) {
  if (routes.length === 0) return null;

  return (
    <div className={styles.wrap}>
      <span className={styles.scoreHintTrigger}>
        <FieldLabel label="おすすめ度について" description={SCORE_HINT} />
      </span>
      {/* value省略時（未選択）はRadixの警告を避けるためundefinedへ正規化する。 */}
      <Tabs.Root
        className={styles.tabs}
        value={selectedRouteId ?? undefined}
        onValueChange={onSelect}
      >
        <Tabs.List className={styles.tabList} aria-label="ルート候補">
          {routes.map((route) => (
            <Tabs.Trigger key={route.id} value={route.id} className={styles.tab}>
              {route.total_score != null && (
                <strong className={styles.tabScore}>おすすめ度 {Math.round(route.total_score)}点</strong>
              )}
              <span className={styles.tabMeta}>
                {/* 改善計画T364/T365: 経由地ルート(route-waypoints)・目的地ルート
                    (route-destination)は候補が常に1件で「方位」という概念が無いため、
                    direction_label（固定文言、route_generator.py参照）をそのまま表示し
                    「方向」は付けない。 */}
                {NON_DIRECTIONAL_ROUTE_IDS.has(route.id) ? route.direction_label : `${route.direction_label}方向`}{" "}
                {route.distance_km.toFixed(1)} km
              </span>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs.Root>
    </div>
  );
}
