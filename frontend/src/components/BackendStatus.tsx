"use client";

import { useEffect, useState } from "react";
import { checkBackendHealth } from "@/services/healthApi";
import styles from "./BackendStatus.module.css";

export default function BackendStatus() {
  const [status, setStatus] = useState<"checking" | "ok" | "ng">("checking");

  useEffect(() => {
    checkBackendHealth().then((ok) => setStatus(ok ? "ok" : "ng"));
  }, []);

  const label = { checking: "確認中...", ok: "Backend: OK", ng: "Backend: NG" }[status];
  const statusClass = { checking: styles.checking, ok: styles.ok, ng: styles.ng }[status];

  return <span className={`${styles.status} ${statusClass}`}>{label}</span>;
}
