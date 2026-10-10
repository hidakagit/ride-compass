// 担当がユーザーに問う（判断）。形に合わなければ何も書かずに断る。本文の頭に回答フォームへのボタンを書いてから、問いをコメントに書く
// （同じ要求の中で並べた順に書くので、問いの通知から開いた時点でボタンがある）。ステータスは、問いを受けたゲートが決める。
// 答えの無い最新の問いが同じ文なら書き直さない——書く要求は失敗の応答でも通っていることがあり（github.js: again）、落ちた打ちを打ち直すと
// 問いが2つになる。
import { addComment, readTask } from "./github.js";
import { bodyRest, checkQuestion, normalize, SCAN, unanswered, withButton } from "./rules.js";

export async function askTask(gh, config, number, question) {
  const problems = checkQuestion(config.questionTemplate, question);
  if (problems.length) throw new Error(`問いが形（tools/flow-gate/question_template.md）に合いません: ${problems.join("・")}`);
  const { issue } = await readTask(gh, config, { number }, { comments: SCAN });
  if (issue?.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の開いた issue ではありません。`);
  const bodies = issue.comments.nodes.map((c) => normalize(c.body).trim());
  const again = unanswered(bodies) && bodies.findLast((b) => b.startsWith("## 問い")) === question;
  const body = withButton(bodyRest(issue.body), `${config.urls.form}/answer?issue=${number}`, `${config.urls.gate}/button.svg`);
  await gh.write([...(body !== normalize(issue.body) ? [["updateIssue", { id: issue.id, body }]] : []), ...(again ? [] : [addComment(issue.id, question)])]);
  return `#${number}: ${again ? "同じ問いがあるので書かなかった" : "問うた"}（回答フォーム: ${config.urls.form}/answer?issue=${number}）`;
}
