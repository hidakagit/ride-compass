// 作業ブランチの Pull Request の出来事でタスクを動かす。マージの前に確かめ終える（コードのリポジトリの必須チェックと、
// 最新の master を取り込む決まり）ので、マージの出来事だけで完了か未着手かが決まり、マージのあとの CI は待たない。
// Pull Request は作業ブランチ（code.branchPrefix + issue の番号）で引く。コードのリポジトリは読むだけ。
import { Gate } from "./gate.js";
import { remaining } from "./rules.js";

// リンクは Markdown の形で書く（URL をそのまま書くと、GitHub は直後の全角の文字まで URL に含めて開けないリンクにする）。
const prLink = (pr) => `[#${pr.number} ${pr.title.replace(/[[\]]/g, "\\$&")}](${pr.html_url})`;

// 開いた（開き直された）→ 検証中へ（表で行けるのは進行中からだけ）。マージされずに閉じた → 未着手へ。マージされた → 残り（チェックの
// 無い完了の条件）が無ければ完了、あれば未着手へ（Claude が残りを済ませる）。閉じたときは検証中のタスクだけを動かす
// （先に問いを置いて回答待ちになっていれば、答えを待つ）。行けるかは、ほかの経路と同じ照らし（gate.apply → judge）で決まる。
export async function pullRequest(env, config, action, pr) {
  const { branchPrefix } = config.code;
  const number = pr.head.ref.startsWith(branchPrefix) && Number(pr.head.ref.slice(branchPrefix.length));
  if (!number) return "作業ブランチの Pull Request ではない";
  const gate = await Gate.open(env, config);
  const issue = await gate.read({ number });
  if (!issue?.item || issue.state !== "OPEN") return "動かすものは無い";
  const go = async (to, comment, close) => {
    if (action === "closed" && issue.status !== config.review) return `#${number} は「${issue.status}」なので動かさない`;
    const r = await gate.apply(issue, to, { close, comments: comment ? [comment] : [] });
    return r.ok ? `#${number} → ${to}` : `#${number} を動かさなかった（${r.reason}）`;
  };
  if (action !== "closed") return go(config.review);
  if (!pr.merged) return go(config.todo, `Pull Request ${prLink(pr)} がマージされずに閉じられました。コメントを読んでやり直してください。`);
  const left = remaining(config, issue);
  if (!left.length) return go(config.done, `Pull Request ${prLink(pr)} をマージしました。完了にします。`, "COMPLETED");
  return go(config.todo, `Pull Request ${prLink(pr)} をマージしました。次が残っているので Claude に戻します。\n\n${left.map((l) => `- ${l}`).join("\n")}`);
}
