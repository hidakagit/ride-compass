"use client";

import { useEffect, useState } from "react";
import { checkBackendHealth } from "@/services/healthApi";

export default function BackendStatus() {
  const [status, setStatus] = useState<"checking" | "ok" | "ng">("checking");

  useEffect(() => {
    checkBackendHealth().then((ok) => setStatus(ok ? "ok" : "ng"));
  }, []);

  const label = { checking: "確認中...", ok: "Backend: OK", ng: "Backend: NG" }[status];
  const color = { checking: "#888", ok: "#16a34a", ng: "#dc2626" }[status];

  return (
    <span style={{ color, fontWeight: 600 }}>
      {label}
    </span>
  );
}
