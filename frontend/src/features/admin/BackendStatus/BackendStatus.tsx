"use client";

import { useQuery } from "@tanstack/react-query";
import { checkBackendHealth } from "@/features/admin/adminApi";
import { cn } from "@/lib/cn";
import { getQueryClient } from "@/lib/queryClient";

export default function BackendStatus() {
  const { data: healthy } = useQuery({ queryKey: ["backend-health"], queryFn: checkBackendHealth }, getQueryClient());
  const status = healthy === undefined ? "checking" : healthy ? "ok" : "ng";

  // 正常時は静かに（小さく・淡く）、異常時だけ目立たせる。常時「OK」を主張する必要は無く、
  // ユーザーが気にすべきは「使えない理由」があるときだけという考え方。
  const label = { checking: "サーバー接続を確認中…", ok: "サーバー接続: OK", ng: "サーバーに接続できません" }[status];
  const statusClass = {
    checking: "text-[var(--color-muted-strong)]",
    ok: "text-[var(--color-muted)]",
    ng: "font-semibold text-[var(--color-danger)]",
  }[status];

  return <span className={cn("text-[length:var(--font-size-sm)]", statusClass)}>{label}</span>;
}
