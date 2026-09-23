"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import BackendLogsPanel from "@/components/BackendLogsPanel/BackendLogsPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import SystemStatusPanel from "@/components/SystemStatusPanel/SystemStatusPanel";
import AxisStudio from "@/components/AxisStudio/AxisStudio";
import MaterialCoveragePanel from "@/components/AxisStudio/MaterialCoveragePanel";
import DerivedDataFreshnessPanel from "@/components/AxisStudio/DerivedDataFreshnessPanel";
import DbStatusPanel from "@/components/AxisStudio/DbStatusPanel";
import TileCachePanel from "@/components/AxisStudio/TileCachePanel";
import TuningPanel from "@/components/AxisStudio/TuningPanel";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { buttonVariants } from "@/components/ui/Button/Button";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";

// 軸スタジオ・研究モード・開発者向け機能をまとめた独立URLの管理画面。一般向けメイン
// ページ（/）とはURLレベルで分離しており、権限制御はこのルーティング境界
// （src/proxy.ts、matcher: ["/admin","/admin/:path*"]）にHTTP Basic認証として敷いている
// （環境変数ADMIN_BASIC_AUTH_USERNAME/PASSWORD未設定時は常に到達不可）。
export default function AdminPage() {
  const debugEnabled = useDebugEnabled();
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-3xl flex-col gap-4 p-4">
      <h1 className={textVariants({ variant: "title" })}>軸スタジオ・研究/開発者ツール</h1>

      <Tabs className="flex flex-col gap-3" defaultValue="axisStudio">
        <TabsList>
          <TabsTrigger value="axisStudio">軸スタジオ</TabsTrigger>
          <TabsTrigger value="materials">材料</TabsTrigger>
          <TabsTrigger value="tuning">較正値</TabsTrigger>
          <TabsTrigger value="maintenance">データ保守</TabsTrigger>
          <TabsTrigger value="research">研究</TabsTrigger>
          <TabsTrigger value="developer">開発者</TabsTrigger>
        </TabsList>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3")} value="axisStudio">
          <AxisStudio />
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3")} value="materials">
          <MaterialCoveragePanel />
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3")} value="tuning">
          <TuningPanel />
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3")} value="maintenance">
          <DerivedDataFreshnessPanel />
          <DbStatusPanel />
          <TileCachePanel />
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3")} value="research">
          <ResearchPanel />
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3")} value="developer">
          <div className={cn(textVariants({ variant: "hint" }), "flex flex-wrap items-center gap-3")}>
            <div className="inline-flex items-center gap-2">
              <DebugPanel />
              <Toggle
                variant="plain"
                className={buttonVariants({ size: "sm" })}
                pressed={systemStatusOpen}
                onClick={() => setSystemStatusOpen((v) => !v)}
              >
                {systemStatusOpen ? "システム状況を隠す" : "システム状況を表示"}
              </Toggle>
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
            <p className={textVariants({ variant: "hint" })}>
              デバッグログの表示はトップページ（/）のヘッダーアイコンで行えます。
            </p>
          )}
          <SystemStatusPanel open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
          <BackendLogsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
