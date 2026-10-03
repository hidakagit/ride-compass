import { openChildren } from "./rules.js";

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

// 作る担当のタスクをどう動かすか（move.js の行き先と理由。動かさないなら null）。進行中のタスクにだけ使う。verdict は classify の結果、children は
// タスクの子（段階）。担当の外の失敗なら戻す。開いた子があれば、担当は段階に分けて終えたので、親は進行中のまま置く。
// それ以外は落ちたとみなして保留にする。
export function settle(config, { verdict, children, url, jobStatus }) {
  if (verdict.outside) return { to: config.todo, reason: `Actions の作る担当（実行 ${url}）が${verdict.reason}。担当の仕事の外の失敗なので未着手へ戻す` };
  if (openChildren(children).length) return null;
  return { to: config.hold, reason: `Actions の作る担当（実行 ${url}）が、Pull Request も問いも出さずに終わった（結果: ${jobStatus}${jobStatus === "cancelled" ? "。持ち時間を超えたか、Cancel された" : ""}）` };
}

// 担当の最後の発言。result の result（担当が最後に返した文）、無ければ最後の担当の発言の文。長ければ頭から limit 字で切る。
export function lastWords(messages, limit = 2000) {
  if (!Array.isArray(messages)) return null;
  const result = messages.findLast((m) => m?.type === "result");
  const said = messages
    .filter((m) => m?.type === "assistant")
    .map((m) => (m.message?.content ?? []).filter((c) => c?.type === "text").map((c) => c.text).join("\n").trim())
    .findLast((t) => t);
  const text = (typeof result?.result === "string" && result.result.trim()) || said;
  if (!text) return null;
  return text.length > limit ? `${text.slice(0, limit)}…（${text.length}字のうち頭の${limit}字）` : text;
}

const minutes = (ms) => {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}分${s % 60}秒`;
};

// 子の node（move.js 等）が断ったときの理由の1行。捕まえない例外の出力は、例外の行のあとに積み跡と Node.js の版の行が続くので、
// 行頭の「<名前>Error: 」の行を採る（Error はその後ろの文だけ）。その行が無い（process.exit で終えた使い方の誤り等）なら、最後の行を採る。
export function refusal(e) {
  const lines = String(e?.stderr || e?.message || e).trim().split("\n");
  const thrown = lines.map((l) => l.match(/^(\w*Error): (.+)$/)).find(Boolean);
  if (thrown) return thrown[1] === "Error" ? thrown[2] : thrown[0];
  return lines.at(-1);
}

// 後始末が issue へ書く「終わり」のコメント。置き場は非公開なので担当の発言を書いてよい（公開の Actions の記録には出さない）。
// done は後始末がしたことの行、status は終わったときのステータス、elapsedMs は実行の開始からの時間（分からなければ null）。
export function endReport({ kind, url, jobStatus, messages, done, status, elapsedMs }) {
  const result = Array.isArray(messages) ? messages.findLast((m) => m?.type === "result") : null;
  const words = lastWords(messages);
  return [
    `### ${kind}担当の終わり`,
    "",
    "| | |",
    "|---|---|",
    `| 終わったときのステータス | ${status ?? "不明"} |`,
    `| 後始末がしたこと | ${done.length ? done.map((d) => d.replaceAll("|", "\\|")).join("<br>") : "なし"} |`,
    `| ジョブの結果 | ${jobStatus} |`,
    `| かかった時間（実行の開始から） | ${elapsedMs == null ? "不明" : minutes(elapsedMs)} |`,
    `| 手数 | ${result?.num_turns ?? "不明（実行のファイルに result が無い）"} |`,
    `| 実行 | ${url} |`,
    "",
    "担当の最後の発言:",
    "",
    words ? words.split("\n").map((l) => `> ${l}`).join("\n") : "（無い）",
  ].join("\n");
}

// 担当のワークフローが引き受けたとき issue へ書く「着手」のコメント。
export const startReport = ({ kind, url }) => `### ${kind}担当の着手\n\n実行: ${url}`;
