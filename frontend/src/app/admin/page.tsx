"use client";

import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import BackendLogsPanel from "@/components/BackendLogsPanel/BackendLogsPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import SystemStatusPanel from "@/components/SystemStatusPanel/SystemStatusPanel";
import AxisStudio from "@/components/AxisStudio/AxisStudio";
import MaterialCoveragePanel from "@/components/AxisStudio/MaterialCoveragePanel";
import DerivedDataFreshnessPanel from "@/components/AxisStudio/DerivedDataFreshnessPanel";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import styles from "./admin.module.css";

// 軸スタジオ・研究モード・開発者向け機能をまとめた独立URLの管理画面。一般向けメイン
// ページ（/）とはURLレベルで分離しており、権限制御はこのルーティング境界
// （src/proxy.ts、matcher: ["/admin","/admin/:path*"]）にHTTP Basic認証として敷いている
// （環境変数ADMIN_BASIC_AUTH_USERNAME/PASSWORD未設定時は常に到達不可）。
export default function AdminPage() {
  const debugEnabled = useDebugEnabled();
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>軸スタジオ・研究/開発者ツール</h1>

      <Tabs.Root className={styles.tabs} defaultValue="axisStudio">
        <Tabs.List className={styles.tabList}>
          <Tabs.Trigger className={styles.tabTrigger} value="axisStudio">
            軸スタジオ
          </Tabs.Trigger>
          <Tabs.Trigger className={styles.tabTrigger} value="materials">
            材料
          </Tabs.Trigger>
          <Tabs.Trigger className={styles.tabTrigger} value="freshness">
            鮮度
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

        <Tabs.Content className={styles.tabPanel} value="materials">
          <MaterialCoveragePanel />
        </Tabs.Content>

        <Tabs.Content className={styles.tabPanel} value="freshness">
          <DerivedDataFreshnessPanel />
        </Tabs.Content>

        <Tabs.Content className={styles.tabPanel} value="research">
          <ResearchPanel />
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
            // デバッグログ（地図の表示イベント・API呼び出しのライブログ）はDebugConsole
            // 自体が地図インスタンスに紐づく情報のため、地図の無いこのページへ置いても
            // 記録先lib/debugLog.tsがタブ間で共有されず実質機能しない。「/admin=デバッグ
            // モードの設定」「/=地図を操作しながら見るライブログ本体」という役割分担にし、
            // 閲覧はトップページ（/）で行う（デバッグモードのON/OFF自体は上のDebugPanelが
            // localStorage経由でトップページと共有する）。
            <p className={styles.hint}>デバッグログの表示はトップページ（/）のヘッダーアイコンで行えます。</p>
          )}
          <SystemStatusPanel open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
          <BackendLogsPanel />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
