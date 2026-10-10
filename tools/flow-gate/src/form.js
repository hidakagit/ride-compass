// 回答フォーム（Cloudflare Access の内側の Worker）。問いの種類ごとに要るものだけを出し、次のステータスは出さない（要件 R11）。
// 答えはユーザーの名義（env.FORM_TOKEN）でコメントに書き、行き先はゲートがその答えから決める。
import { GitHub } from "./github.js";
import { bodyRest, confirmItems, latestQuestion } from "./questions.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const radios = (name, values) => values.map((v, i) => `<label><input type="radio" name="${name}" value="${esc(v)}"${i ? "" : " checked"}> ${esc(v)}</label>`).join("");
// 答えで選べるのは続けるか保留だけ。やめる（見送り）・終えるは、ユーザーが GitHub の画面で閉じるかボードで完了へ動かす（docs/conventions/flow.md「ステータスと割り当て」）。
const CHOICES = { 採否: ["やる", "保留"], イレギュラー: ["もう一度やる", "保留"] };
const page = (title, inner) => new Response(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:720px;margin:0 auto;padding:16px}label{display:block;margin:6px 0}textarea,input[type=text]{width:100%;box-sizing:border-box}
fieldset{border:1px solid #ccc;border-radius:8px;margin:12px 0}button{font-size:17px;padding:10px 24px;border-radius:8px;border:0;background:#1f6feb;color:#fff}details{margin:12px 0}</style>${inner}`,
{ headers: { "content-type": "text/html; charset=utf-8" } });

async function read(gh, config, number) {
  const [o, n] = config.tasks.split("/");
  const r = await gh.gql(`query($o:String!,$n:String!,$i:Int!){repository(owner:$o,name:$n){issue(number:$i){title body comments(last:40){nodes{body}}}}}`, { o, n, i: number });
  const issue = r.repository.issue;
  const comments = issue.comments.nodes.map((c) => c.body);
  return { issue, comments, question: latestQuestion(comments) };
}

const html = (gh, text) => (text ? gh.rest("POST", "/markdown", { text, mode: "gfm" }) : "");

export async function answerForm(request, env, config) {
  const url = new URL(request.url);
  const number = Number(url.searchParams.get("issue"));
  const gh = await GitHub.app(env, config.installation);
  const { issue, comments, question: q } = await read(gh, config, number);
  if (!q || q.answer) return page("問いはありません", `<p>#${number} に、答えていない問いはありません。</p>`);
  const items = confirmItems(issue.body);
  if (request.method === "POST") {
    const form = await request.formData();
    if (form.get("question") !== q.text) return page("問いが変わりました", `<p>開いたあとに新しい問いが来ました。開き直してください。</p>`);
    const lines = ["## 回答", `**${q.text}**`, ""];
    if (form.get("choice")) lines.push(`回答: ${form.get("choice")}`);
    items.forEach((item, i) => lines.push(form.get(`ok${i}`) === "よい" ? `- よい: ${item}` : `- よくない: ${item} — ${form.get(`note${i}`) || "（理由なし）"}`));
    if (form.get("note")) lines.push(`補足: ${form.get("note")}`);
    await new GitHub(env.FORM_TOKEN).rest("POST", `/repos/${config.tasks}/issues/${number}/comments`, { body: lines.join("\n") });
    return page("送りました", `<p>#${number} に答えを書きました。行き先はゲートが決めます。</p><p><a href="https://github.com/${config.tasks}/issues/${number}">issue を開く</a></p>`);
  }
  const ask = q.kind === "判断" ? (q.plans.length ? radios("choice", [...q.plans, "どれでもない（補足に書く）"]) : "")
    : q.kind === "確かめ" ? items.map((item, i) => `<fieldset><legend>${esc(item)}</legend>${radios(`ok${i}`, ["よい", "よくない"])}
      <input type="text" name="note${i}" placeholder="よくなければ、何がおかしいか"></fieldset>`).join("")
    : radios("choice", CHOICES[q.kind]);
  const recent = q.kind === "イレギュラー" ? comments.findLast((c) => /^### \S+担当の終わり/.test(c)) : null;
  // Markdown の描画は互いに独立なので並べて打つ。
  const [said, material, body] = await Promise.all([html(gh, recent), html(gh, q.material), html(gh, bodyRest(issue.body))]);
  return page(`#${number} ${issue.title}`, `<h1>#${number} ${esc(issue.title)}</h1><h2>${esc(q.text)}</h2>
${said ? `<section>${said}</section>` : ""}
<details><summary>判断材料</summary>${material}</details>
<details><summary>issue の本文</summary>${body}</details>
<form method="post"><input type="hidden" name="question" value="${esc(q.text)}">${ask}
<label>補足<textarea name="note" rows="3"></textarea></label><button>答える</button></form>`);
}
