// 作業ブランチの Pull Request の出来事でタスクを動かす。マージの前に確かめ終える（コードのリポジトリの必須チェックと、
// 最新の master を取り込む決まり）ので、マージの出来事だけで完了か未着手かが決まり、マージのあとの CI は待たない。
// Pull Request は作業ブランチ（code.branchPrefix + issue の番号）で引く。コードのリポジトリは読むだけ。
import { Gate } from "./gate.js";
import { check, remaining } from "./rules.js";

// タスクの作業ブランチの、いちばん新しい Pull Request（閉じたもの・マージしたものも含む）。無ければ undefined。
export async function latestPr(code, config, number) {
  const { repository, branchPrefix } = config.code;
  const owner = repository.split("/")[0];
  const [pr] = await code.rest("GET", `/repos/${repository}/pulls?head=${owner}:${branchPrefix}${number}&state=all&sort=created&direction=desc&per_page=1`);
  return pr;
}

// リンクは Markdown の形で書く（URL をそのまま書くと、GitHub は直後の全角の文字まで URL に含めて開けないリンクにする）。
const prLink = (pr) => `[#${pr.number} ${pr.title.replace(/[[\]]/g, "\\$&")}](${pr.html_url})`;

// 開いた（開き直された）→ 検証中。マージされずに閉じた → 未着手。マージされた → 残り（チェックの無い完了の条件・ユーザーの確認）が
// 無ければ完了、あれば未着手（Claude が残りを済ませる）。表で行けない出来事（進行中でない issue の Pull Request 等）は何もしない。
export async function pullRequest(env, config, origin, action, pr) {
  const { branchPrefix } = config.code;
  const number = pr.head.ref.startsWith(branchPrefix) && Number(pr.head.ref.slice(branchPrefix.length));
  if (!number) return "作業ブランチの Pull Request ではない";
  const gate = await Gate.open(env, config, origin);
  const issue = await gate.read({ number });
  if (!issue?.item || issue.state !== "OPEN") return "動かすものは無い";
  // 行き先は表の行から取る（マージだけは完了とそれ以外の2つ）。
  const to = (on, done = false) => config.transitions.find((t) => t.on === on).to.find((s) => (s === config.done) === done);
  const go = async (on, done, comment, close) => {
    const next = to(on, done);
    if (!check(config, issue.status, next, { on }).ok) return `#${number} は「${issue.status}」なので動かさない`;
    await gate.apply(issue, issue.status, next, { on, close, comments: comment ? [comment] : [] });
    return `#${number} ${on} → ${next}`;
  };
  if (action !== "closed") return go("PR が開いた");
  if (!pr.merged) return go("PR が閉じた", false, `Pull Request ${prLink(pr)} がマージされずに閉じられました。コメントを読んでやり直してください。`);
  const left = remaining(config, issue);
  if (!left.length) return go("マージ", true, `Pull Request ${prLink(pr)} をマージしました。完了にします。`, "COMPLETED");
  return go("マージ", false, `Pull Request ${prLink(pr)} をマージしました。次が残っているので Claude に戻します。\n\n${left.map((l) => `- ${l}`).join("\n")}`);
}
