"use client";

import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { Card } from "@/components/ui/Card/Card";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import SystemStatusPanel from "@/components/SystemStatusPanel/SystemStatusPanel";
import WeightPanel, { DEFAULT_SCORING_WEIGHTS } from "@/components/WeightPanel/WeightPanel";
import AxisStudio from "@/components/AxisStudio/AxisStudio";
import { useStoredJsonState } from "@/hooks/useStoredState";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import type { ScoringWeights } from "@/types/route";
import styles from "./admin.module.css";

// 軸スタジオ・研究モード・開発者向け機能をまとめた独立URLの管理画面（改善計画T270、
// 目論見書4章「軸スタジオ」）。一般向けメインページ（/）とはURLレベルで分離しており、
// 権限制御（改善計画T272、2026-08-24完了）はこのルーティング境界（src/proxy.ts、
// matcher: ["/admin","/admin/:path*"]）にHTTP Basic認証として敷いている
// （環境変数ADMIN_BASIC_AUTH_USERNAME/PASSWORD未設定時は常に到達不可）。
// 研究モード・評価重みの各stateはlocalStorage経由でメインページと共有する
// ——同じキーでuseStoredJsonStateを呼ぶことで、ここでの編集が次回メインページを開いたとき/
// 再読み込みしたときに反映される。同一タブでのリアルタイム同期ではない点はlib/researchMode.ts
// 等の既存パターンと同じ）。
export default function AdminPage() {
  const researchEnabled = useResearchEnabled();
  const debugEnabled = useDebugEnabled();
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);

  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredJsonState(
    "ridecompass:weight-override-enabled",
    false
  );
  const [scoringWeights, setScoringWeights] = useStoredJsonState<ScoringWeights>(
    "ridecompass:scoring-weights",
    DEFAULT_SCORING_WEIGHTS
  );

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>軸スタジオ・研究/開発者ツール</h1>

      {/* 改善計画T397フォローアップ2（ユーザー指摘: 説明文が多い・研究/開発者もタブに
          したい・下に行き過ぎて使いにくい）: ヘッダーの説明文（独立URL・localStorage
          経由の話）を撤去し、3つのDisclosure（縦積みの折りたたみ）をやめて同じ高さに
          並ぶタブへ再構成した。 */}
      <Tabs.Root className={styles.tabs} defaultValue="axisStudio">
        <Tabs.List className={styles.tabList}>
          <Tabs.Trigger className={styles.tabTrigger} value="axisStudio">
            軸スタジオ
          </Tabs.Trigger>
          <Tabs.Trigger className={styles.tabTrigger} value="research">
            研究
          </Tabs.Trigger>
          <Tabs.Trigger className={styles.tabTrigger} value="developer">
            開発者
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content className={styles.tabPanel} value="axisStudio">
          <AxisStudio />
        </Tabs.Content>

        <Tabs.Content className={styles.tabPanel} value="research">
          <ResearchPanel />
          {researchEnabled && (
            <Card>
              <WeightPanel
                overrideEnabled={weightOverrideEnabled}
                onOverrideEnabledChange={setWeightOverrideEnabled}
                scoringWeights={scoringWeights}
                onScoringWeightsChange={setScoringWeights}
              />
            </Card>
          )}
          {!researchEnabled && (
            <p className={styles.hint}>
              研究モードは現在OFFです。上のチェックボックスで有効にすると評価重みの調整パネルが
              現れます。
            </p>
          )}
        </Tabs.Content>

        <Tabs.Content className={styles.tabPanel} value="developer">
          <div className={styles.systemRow}>
            <div className={styles.debugControl}>
              <DebugPanel />
              <button type="button" onClick={() => setSystemStatusOpen((v) => !v)} aria-pressed={systemStatusOpen}>
                {systemStatusOpen ? "システム状況を隠す" : "システム状況を表示"}
              </button>
            </div>
            <BackendStatus />
          </div>
          {debugEnabled && (
            // 改善計画T278レビュー指摘の修正（2026-08-24）: デバッグログ（地図の表示
            // イベント・API呼び出しのライブログ）はDebugConsole自体が地図インスタンスに
            // 紐づく情報のため、地図の無いこのページへ置いても記録先lib/debugLog.tsが
            // タブ間で共有されず実質機能しなかった。「/admin=デバッグモードの設定」
            // 「/=地図を操作しながら見るライブログ本体」という役割分担にし、閲覧はトップ
            // ページ（/）で行う（デバッグモードのON/OFF自体は上のDebugPanelがlocalStorage
            // 経由でトップページと共有する）。トップページ側の起動導線は改善計画T300で
            // 「開発者」ブロック（旧称「設定」）廃止に伴い、常設ヘッダーのアイコンボタンへ
            // 移設済み。
            <p className={styles.hint}>デバッグログの表示はトップページ（/）のヘッダーアイコンで行えます。</p>
          )}
          <SystemStatusPanel open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
