"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card/Card";
import { Input } from "@/components/ui/Input/Input";
import { Button } from "@/components/ui/Button/Button";
import { getRecentLogs, type LogLevelName } from "@/services/debugAdminApi";
import styles from "./BackendLogsPanel.module.css";

const DEFAULT_LIMIT = 200;
const LOG_LEVEL_OPTIONS: readonly LogLevelName[] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

// フロントのDebugConsole（lib/debugLog.ts、entry.level="info"/"warn"/"error"）と同じ
// 「レベルで色分けする」見た目に揃える（改善計画T517、ユーザー指摘「フロントのログ画面と
// 統一して、色で区別でもOK」）。backendの整形済みログ行（debug_control.py: _LOG_FORMAT）は
// 先頭付近に"[LEVELNAME]"を含むため、そこから正規表現で取り出す。
const LEVEL_PATTERN = /\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]/;

function parseLogLevel(line: string): LogLevelName | null {
  const match = line.match(LEVEL_PATTERN);
  return (match?.[1] as LogLevelName | undefined) ?? null;
}

// 「開発者」タブからbackendの直近ログ（GET /api/admin/debug/logs、T379）を見られる
// パネル（改善計画T517、ユーザー指摘「バックエンドのログを見るのに、サーバに毎回入らないと
// だめなのはキツい」）。/adminページ自体が既にブラウザ標準のBasic認証で保護されているため、
// 認証情報の入力欄は持たない（axisAdminApi.tsと同じ理由、debugAdminApi.tsのコメント参照）。
// 取得は開いたとき自動ではなく「取得」ボタン押下時のみ（SystemStatusPanelと同じ、
// プロセス内スナップショットのためポーリング不要）。
export default function BackendLogsPanel() {
  const [contains, setContains] = useState("");
  const [minLevel, setMinLevel] = useState<LogLevelName | "">("WARNING");
  const [limit, setLimit] = useState(String(DEFAULT_LIMIT));
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleFetch = () => {
    setLoading(true);
    setError(null);
    const parsedLimit = Number(limit);
    getRecentLogs({
      contains: contains.trim() || undefined,
      minLevel: minLevel || undefined,
      limit: Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : undefined,
    })
      .then((result) => setLines(result))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <Card className={styles.panel}>
      <div className={styles.heading}>バックエンドの直近ログ</div>
      <p className={styles.hint}>
        debug_modeがOFFの間もWARNING以上（エラー・429拒否等）は記録されている。DEBUGレベルの
        詳細を見るには上の「デバッグログを表示」ではなく、backend側でdebug_modeを有効化する
        必要がある（`POST /api/admin/debug/mode`、このパネルの対象外）。
      </p>
      <div className={styles.controls}>
        <select
          value={minLevel}
          onChange={(e) => setMinLevel(e.target.value as LogLevelName | "")}
          className={styles.levelSelect}
          aria-label="最小レベル"
        >
          <option value="">すべてのレベル</option>
          {LOG_LEVEL_OPTIONS.map((level) => (
            <option key={level} value={level}>
              {level}以上
            </option>
          ))}
        </select>
        <Input
          type="text"
          placeholder="絞り込み（部分一致、例: jma-tile）"
          value={contains}
          onChange={(e) => setContains(e.target.value)}
          className={styles.containsInput}
        />
        <Input
          type="number"
          min={1}
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
          className={styles.limitInput}
          aria-label="件数"
        />
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "取得中…" : "取得"}
        </Button>
      </div>
      {error && <p className={styles.error}>取得失敗: {error}</p>}
      {lines && lines.length === 0 && !error && <p className={styles.hint}>該当するログはありません。</p>}
      {lines && lines.length > 0 && (
        <div className={styles.logBody}>
          {lines.map((line, i) => (
            <div key={i} className={styles.logLine} data-level={parseLogLevel(line)}>
              {line}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
