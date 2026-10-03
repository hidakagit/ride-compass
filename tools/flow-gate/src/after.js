// 担当のワークフローの後始末で、担当がどう終わったかを見分ける。messages は連携（anthropics/claude-code-action）が書き出す
// 実行のファイル（Agent SDK のメッセージの並び）。担当の発言のメッセージの error（Agent SDK の SDKAssistantMessageError）が
// 担当の仕事の外の失敗なら、タスクは保留にせず未着手へ戻す。利用の上限・認証・課金の失敗は、待つか人が直すまで続くので、
// 振り出しもしばらく止める。混雑・サーバーの失敗は一時のものなので、戻すだけにする。実行のファイルが無い（担当が動けなかった）
// ときも、上限・認証と同じに扱う。
const QUOTA = ["rate_limit", "billing_error", "authentication_failed", "oauth_org_not_allowed", "account_on_hold"];
const TRANSIENT = ["overloaded", "server_error"];

// 返すのは { outside: 担当の外の失敗か, pause: 振り出しを止めるか, reason: 1行 }。
export function classify(messages) {
  if (!Array.isArray(messages)) return { outside: true, pause: true, reason: "担当が動けなかった（実行のファイルが無い）" };
  const errors = messages.filter((m) => m?.type === "assistant" && m.error).map((m) => m.error);
  const quota = errors.find((e) => QUOTA.includes(e));
  if (quota) return { outside: true, pause: true, reason: `Claude の利用の上限か認証で止まった（${quota}）` };
  const transient = errors.find((e) => TRANSIENT.includes(e));
  if (transient) return { outside: true, pause: false, reason: `Claude のサーバーの一時の失敗で止まった（${transient}）` };
  return { outside: false, pause: false, reason: "" };
}
