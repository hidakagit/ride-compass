"use client";

import { useState } from "react";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { CopyIcon } from "@/components/ui/icons/icons";
import { Card } from "@/components/ui/Card/Card";
import { Input } from "@/components/ui/Input/Input";
import { Button } from "@/components/ui/Button/Button";
import { getRecentLogs, type LogLevelName } from "@/features/admin/adminApi";
import { vocabulary } from "@/types/generated/vocabulary";
import { Select } from "@/components/ui/Input/Input";
import { LogLine } from "@/components/ui/LogLine/LogLine";
import { textVariants } from "@/components/ui/Text/Text";

const DEFAULT_LIMIT = 200;
// 選択肢は軽い順に並べる。キーの過不足はbackendの契約から引いた型が検査する。
/** 選べるレベル（軽い順）。**backendの宣言の並びそのもの**（生成物`vocabulary.ts`の`logLevels`）。 */
const LOG_LEVEL_OPTIONS: readonly LogLevelName[] = vocabulary.logLevels;

// フロントのDebugConsole（lib/debugLog.ts、entry.level="info"/"warn"/"error"）と同じ
// 「レベルで色分けする」見た目に揃える。backendの整形済みログ行（request_log.py:
// LOG_FORMAT）は先頭付近に"[LEVELNAME]"を含むため、そこから正規表現で取り出す。
const LEVEL_PATTERN = new RegExp(`\\[(${LOG_LEVEL_OPTIONS.join("|")})\\]`);

function logTone(level: LogLevelName | null): "error" | "warning" | "normal" {
  if (level === "ERROR" || level === "CRITICAL") return "error";
  return level === "WARNING" ? "warning" : "normal";
}

function parseLogLevel(line: string): LogLevelName | null {
  const match = line.match(LEVEL_PATTERN);
  return (match?.[1] as LogLevelName | undefined) ?? null;
}

// 「開発者」タブからbackendの直近ログ（GET /api/admin/debug/logs）を見られるパネル。
// /adminページ自体が既にブラウザ標準のBasic認証で保護されているため、認証情報の入力欄は持たない。
// 取得は開いたとき自動ではなく「取得」ボタン押下時のみ（SystemStatusPanelと同じ、
// プロセス内スナップショットのためポーリング不要）。
export default function BackendLogsPanel() {
  const [contains, setContains] = useState("");
  const [minLevel, setMinLevel] = useState<LogLevelName | "">("WARNING");
  const [limit, setLimit] = useState(String(DEFAULT_LIMIT));
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { copied, error: copyError, copy } = useCopyToClipboard();

  const handleFetch = () => {
    setLoading(true);
    setError(null);
    const parsedLimit = Number(limit);
    getRecentLogs({
      contains: contains.trim() || undefined,
      min_level: minLevel || undefined,
      limit: Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : undefined,
    })
      .then((result) => setLines(result))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <Card className="flex flex-col gap-2">
      <div className={textVariants({ variant: "heading" })}>バックエンドの直近ログ</div>
      <p className={textVariants({ variant: "hint" })}>
        debug_modeがOFFの間もWARNING以上（エラー・429拒否等）は記録されている。DEBUGレベルの
        詳細を見るには上の「デバッグログを表示」ではなく、backend側でdebug_modeを有効化する 必要がある（`POST
        /api/admin/debug/mode`、このパネルの対象外）。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={minLevel}
          onChange={(e) => setMinLevel(e.target.value as LogLevelName | "")}
          aria-label="最小レベル"
        >
          <option value="">すべてのレベル</option>
          {LOG_LEVEL_OPTIONS.map((level) => (
            <option key={level} value={level}>
              {level}以上
            </option>
          ))}
        </Select>
        <Input
          type="text"
          placeholder="絞り込み（部分一致、例: jma-tile）"
          value={contains}
          onChange={(e) => setContains(e.target.value)}
          className="min-w-48 flex-1"
        />
        <Input
          type="number"
          min={1}
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
          className="w-24"
          aria-label="件数"
        />
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "取得中…" : "取得"}
        </Button>
      </div>
      {error && <p className={textVariants({ variant: "error" })}>取得失敗: {error}</p>}
      {lines && lines.length === 0 && !error && (
        <p className={textVariants({ variant: "hint" })}>該当するログはありません。</p>
      )}
      {lines && lines.length > 0 && (
        <>
          {/* 行ごとのdivを1件ずつドラッグ選択するのは手間なため、表示中の全行を
              まとめてクリップボードへコピーするボタンを用意する。 */}
          <div className="flex justify-end">
            <Button
              variant="secondary"
              onClick={() => copy(lines.join("\n"))}
              aria-label={copied ? "ログ全体をコピーしました" : "ログ全体をコピー"}
              title={copied ? "コピーしました" : "ログ全体をコピー"}
            >
              <CopyIcon size={14} />
            </Button>
          </div>
          {/* ログ取得の失敗（error）とは原因も対処も別なので、同じ行へ混ぜない。 */}
          {copyError && <p className={textVariants({ variant: "error" })}>{copyError}</p>}
          <div className="max-h-96 overflow-auto rounded-sm border border-[var(--color-border-muted)] bg-[var(--color-surface)] p-2">
            {lines.map((line, i) => (
              <LogLine key={i} tone={logTone(parseLogLevel(line))} data-level={parseLogLevel(line)}>
                {line}
              </LogLine>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
