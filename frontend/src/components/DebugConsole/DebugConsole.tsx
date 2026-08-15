"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { clearDebugLog } from "@/lib/debugLog";
import { getDebugStats, type DebugStats } from "@/services/debugStatsApi";
import styles from "./DebugConsole.module.css";

function formatStartedAt(iso: string): string {
  return new Date(iso).toLocaleString("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// DebugConsole.module.cssの.consoleが持つmax-heightと一致させること。
export const DEBUG_CONSOLE_MAX_HEIGHT_PX = 560;

interface DebugConsoleProps {
  /** パネル自体の開閉（デバッグモードのON/OFFとは別。常時占有させたくないという実機
   * フィードバックを受け、「設定」内のボタンから開閉する、T42） */
  open: boolean;
  onClose: () => void;
}

// デバッグモードON時のみ、地図の上に浮かべて表示するイベントログ。
// マップの表示イベント（初期化・タイル/スタイル要求・パン/ズーム）と外部API呼び出し
// （天候/ルート生成/地域レイヤー/基礎地図）を発生順に積む。DebugPanelのトグルと状態を共有する。
// デバッグモードON＝ログの記録自体は常時有効だが、このパネル表示は別途openで制御する
// （常時ONだと画面の目立つ面積を占有し続けるという実機フィードバック、T42）。
// 一般ユーザーは使わない機能のため、サイドバー/地図に固定するのではなく、ヘッダーの
// つまみでドラッグして動かせる・地図を透かして見られる独立したフローティングパネルにした
// （地図上アイコン列からの分離、モバイル実機フィードバック対応T43）。
export default function DebugConsole({ open, onClose }: DebugConsoleProps) {
  const enabled = useDebugEnabled();
  const entries = useDebugLogEntries();
  const listRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ pointerId: number; startClientX: number; startClientY: number; startLeft: number; startTop: number } | null>(
    null,
  );
  // null=CSSの既定位置（画面上部中央寄せ）。ドラッグすると具体的なtop/leftへ切り替える。
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  // /api/debug/stats（外部API呼び出し件数・エラー数・キャッシュヒット率、適用中のcommit等）。
  // 「天候取得が失敗している」といった調査で、フロント側のイベントログだけでなくバックエンド
  // 側の集計も同じパネルから見られるようにする。プロセス内カウンタなのでポーリングはせず、
  // 開いたときと「更新」ボタン押下時にだけ取得する。
  const [stats, setStats] = useState<DebugStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  const fetchStats = useCallback(() => {
    setStatsLoading(true);
    setStatsError(null);
    getDebugStats()
      .then((data) => setStats(data))
      .catch((error) => setStatsError(error instanceof Error ? error.message : String(error)))
      .finally(() => setStatsLoading(false));
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  // 開き直すたびに既定位置（画面上部中央寄せ）へ戻す。ドラッグ位置は開いている間だけの
  // 一時的な配置という位置づけ（永続化はしない）。effect本体からの直接同期setState呼び出しを
  // 避け、マイクロタスク経由で実行する（react-hooks/set-state-in-effect対策、page.tsxの
  // fetchWeatherForと同じ流儀）。
  useEffect(() => {
    if (open) Promise.resolve().then(() => setPosition(null));
  }, [open]);

  // 開くたびに最新の集計を取る（プロセス内カウンタのため、開きっぱなしの間は「更新」ボタンで
  // 手動更新する想定。ポーリングは常時ONのデバッグモードと相性が悪いため入れない）。
  useEffect(() => {
    if (open) fetchStats();
  }, [open, fetchStats]);

  if (!enabled || !open) return null;

  function handleDragHandlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startLeft: rect.left,
      startTop: rect.top,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function handleDragHandlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    setPosition({
      left: drag.startLeft + (e.clientX - drag.startClientX),
      top: drag.startTop + (e.clientY - drag.startClientY),
    });
  }

  function handleDragHandlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
  }

  return (
    // app-debug-consoleはglobals.css側のモバイル向けタップ領域ルール
    // （.app-sidebar button, .app-debug-console button）が参照するグローバルなマーカー
    // クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
    // 見た目自体はstyles.consoleに任せつつ、このマーカークラスだけ併用している。
    <div
      ref={panelRef}
      className={`${styles.console} app-debug-console`}
      // ドラッグ中はCSSの既定の左右中央寄せ（transform: translateX(-50%)）を打ち消し、
      // top/leftをそのまま画面座標として使う（打ち消さないと中央寄せ分だけ位置がずれる）。
      style={
        position != null ? { top: `${position.top}px`, left: `${position.left}px`, transform: "none" } : undefined
      }
    >
      <div className={styles.header}>
        <div
          className={styles.dragHandle}
          onPointerDown={handleDragHandlePointerDown}
          onPointerMove={handleDragHandlePointerMove}
          onPointerUp={handleDragHandlePointerUp}
          role="separator"
          aria-label="ドラッグしてパネルを移動"
          title="ドラッグして移動"
        >
          ⠿
        </div>
        <strong className={styles.title}>デバッグログ（{entries.length}件）</strong>
        <div className={styles.headerButtons}>
          <button type="button" onClick={clearDebugLog} className={styles.clearButton}>
            クリア
          </button>
          <button type="button" onClick={onClose} aria-label="デバッグログを閉じる" className={styles.closeButton}>
            ✕
          </button>
        </div>
      </div>
      <div className={styles.stats}>
        <div className={styles.statsHeader}>
          <span>システム状況</span>
          <button type="button" onClick={fetchStats} disabled={statsLoading} className={styles.statsRefreshButton}>
            {statsLoading ? "更新中…" : "更新"}
          </button>
        </div>
        {statsError && <p className={styles.statsError}>取得失敗: {statsError}</p>}
        {stats && (
          <>
            <p className={styles.statsLine}>
              commit {stats.commit ?? "(ローカル)"} ・ engine {stats.engine} ・ 起動 {formatStartedAt(stats.started_at)}
            </p>
            {Object.entries(stats.external).map(([category, s]) => (
              <p key={category} className={styles.statsLine} data-level={s.errors > 0 ? "error" : undefined}>
                <span className={styles.entryCategory}>{category}</span> 呼出{s.calls} エラー{s.errors}
                {s.cache_hit_rate != null && ` hit${Math.round(s.cache_hit_rate * 100)}%`} 平均{s.avg_ms}ms 最大
                {s.max_ms}ms
              </p>
            ))}
            {Object.entries(stats.rate_limit_rejections).map(([category, count]) => (
              <p key={category} className={styles.statsLine} data-level="warn">
                429拒否: {category} {count}件
              </p>
            ))}
          </>
        )}
      </div>
      <div ref={listRef} className={styles.entries}>
        {entries.length === 0 && <p className={styles.emptyMessage}>イベント待機中...（地図を操作するかAPIを呼び出してください）</p>}
        {entries.map((entry) => (
          <div key={entry.id} className={styles.entry} data-level={entry.level}>
            <span className={styles.entryTime}>{entry.time}</span> <span className={styles.entryCategory}>[{entry.category}]</span>{" "}
            <span className={styles.entryMessage}>{entry.message}</span>
            {entry.detail != null && <span className={styles.entryDetail}> {JSON.stringify(entry.detail)}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
