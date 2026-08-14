"use client";

import { useEffect, useState } from "react";
import { checkBackendHealth } from "@/services/healthApi";
import styles from "./BackendStatus.module.css";

export default function BackendStatus() {
  const [status, setStatus] = useState<"checking" | "ok" | "ng">("checking");

  useEffect(() => {
    // React 18 Strict Mode（開発時）はこの副作用をマウント→クリーンアップ→再マウントで
    // 2回実行する。クリーンアップ済みの古い方の結果が後から届いて新しい結果を上書きする
    // 競合が実機で発生した（例: 新しい方がok→古い方がタイムアウトでngになりngのまま固定）
    // ため、クリーンアップ後は結果を反映しないようにガードする。
    let cancelled = false;
    checkBackendHealth().then((ok) => {
      if (!cancelled) setStatus(ok ? "ok" : "ng");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const label = { checking: "確認中...", ok: "Backend: OK", ng: "Backend: NG" }[status];
  const statusClass = { checking: styles.checking, ok: styles.ok, ng: styles.ng }[status];

  return <span className={`${styles.status} ${statusClass}`}>{label}</span>;
}
