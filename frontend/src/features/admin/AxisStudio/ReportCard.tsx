"use client";

import { type ReactNode, useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { textVariants } from "@/components/ui/Text/Text";
import { formatJstDateTime } from "@/lib/time";

/** 件数・行数（3桁区切り）。数えられなかったものは「-」。 */
export function formatCount(value: number | null): string {
  return value === null ? "-" : value.toLocaleString("ja-JP");
}

/** backendが返した時点（ISO）を日本時間で。記録が無ければその旨。 */
export function formatMoment(iso: string | null): string {
  return iso ? formatJstDateTime(new Date(iso)) : "記録なし";
}

/**
 * 「データ保守」「材料」タブの集計のカード。集計はDB全体の走査を伴うため、開いたときには取らず「集計する」を
 * 押したときだけ取る。説明はⓘの奥に置き、集計の時刻（と`summary`があれば母数）をボタンの横に出す。
 */
export function ReportCard<T extends { computed_at: string }>({
  title,
  info,
  load,
  summary,
  children,
}: {
  title: string;
  info: ReactNode;
  load: () => Promise<T>;
  summary?: (report: T) => string;
  children: (report: T) => ReactNode;
}) {
  const [report, setReport] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleFetch = () => {
    setLoading(true);
    setError(null);
    load()
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <span className={textVariants({ variant: "heading" })}>{title}</span>
        <InfoPopover triggerAriaLabel={`${title}の説明`}>{info}</InfoPopover>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "集計中…" : report ? "再集計する" : "集計する"}
        </Button>
        {report && (
          <span className={textVariants({ variant: "hint" })}>
            {[summary?.(report), formatMoment(report.computed_at)].filter(Boolean).join(" ・ ")}
          </span>
        )}
      </div>
      {error && <p className={textVariants({ variant: "error" })}>集計失敗: {error}</p>}
      {report && children(report)}
    </Card>
  );
}
