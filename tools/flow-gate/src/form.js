// 回答フォーム（Cloudflare Access の内側の Worker）。見た目と流れはユーザーと合意したモック（tasks#799 のコメントの Artifact。前の v3・v4 の形）:
// スマホの幅で1列・材料と選ぶ行は下の区切り線だけ・補足は2行・「確認」で入力を固めて戻る／送信を横に並べ・送ったあとは結果と「GitHub に戻る」だけ。
// 問いの種類ごとに要るものだけを出し、次のステータスは出さない（tasks#788）。答えはユーザーの名義（env.FORM_TOKEN）でコメントに書き、
// ラベルの付け外しも同じ名義で打つ。行き先はゲートが答えから決める。
import { GitHub } from "./github.js";
import { bodyRest, confirmItems, latestQuestion, norm } from "./questions.js";

const RECENT = 5; // 材料に載せる最近のコメント（上に出した問いのコメントは数えない。tasks#188）
const NONE = "該当なし（補足に記入）";
const CHOICES = { 採否: ["着手する", "保留する", "見送る"], イレギュラー: ["やり直す", "保留する", "見送る"] };
const OK = ["問題なし", "問題あり"];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const when = (t) => new Date(Date.parse(t) + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " "); // 日本時間

const SCRIPT = `<script>
const f = document.querySelector("form"), err = document.getElementById("err");
document.getElementById("go")?.addEventListener("click", () => f.classList.add("lock"));
document.getElementById("back")?.addEventListener("click", () => f.classList.remove("lock"));
f?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!f.classList.contains("lock")) return;
  f.querySelectorAll("button").forEach((b) => (b.disabled = true));
  const j = await (await fetch(location.href, { method: "POST", body: new FormData(f) })).json();
  if (j.error) { err.textContent = j.error; f.classList.remove("lock"); f.querySelectorAll("button").forEach((b) => (b.disabled = false)); return; }
  const p = (text, className = "") => Object.assign(document.createElement("p"), { textContent: text, className });
  // 先にタブを閉じる（移ったあとではこのページが無く、閉じる処理が動かない）。閉じられない開き方なら issue へ移る（tasks#101）。
  const back = Object.assign(document.createElement("button"), { textContent: "GitHub に戻る", className: "sub" });
  back.addEventListener("click", () => (window.close(), setTimeout(() => location.replace(j.url), 300)));
  document.body.replaceChildren(p("受け付けました（" + j.label + "）。"), back, p("押すとこのタブを閉じる。閉じられない開き方のときは issue へ移る。", "note"));
});
</script>`;

const page = (inner, status = 200) => new Response(`<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>回答</title><style>body{font:14px/1.6 system-ui,sans-serif;max-width:34rem;margin:.75rem auto;padding:0 16px}p{margin:0 0 .5rem}
.num,.sec,.note,summary.s{font-size:13px;opacity:.7}.num{font-size:12px;margin:0}.title{font-weight:500;margin:0 0 6px}.sec{margin:14px 0 6px}
details{border-bottom:1px solid #8884;padding:6px 0;overflow-wrap:anywhere}details>div{max-height:40vh;overflow:auto;font-size:13px;margin-top:6px}
.opt{display:flex;gap:8px;align-items:flex-start;padding:7px 0;border-bottom:1px solid #8884;overflow-wrap:anywhere}.item{padding:8px 0;border-bottom:1px solid #8884}
.item>p{font-size:13px;margin:0 0 6px}textarea,input[type=text]{width:100%;box-sizing:border-box;font:inherit;margin-top:8px}
.seg{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;border:1px solid #8888;border-radius:8px;overflow:hidden}
.seg label{text-align:center;font-size:13px;padding:8px 0}.seg label+label{border-left:1px solid #8888}.seg input{position:absolute;opacity:0;pointer-events:none}
.seg label:has(input:checked){background:#1f6feb22;color:#1f6feb}.labels{border:0;margin-top:6px}.labels>div{display:flex;flex-wrap:wrap;gap:10px}
#err{font-size:13px;color:#d1242f;min-height:1em;margin:8px 0 0}button{display:block;width:100%;padding:8px;margin-top:4px;border-radius:8px;font:inherit}
.sub{background:transparent;color:inherit;border:1px solid #8888}.main{background:#1f6feb;color:#fff;border:0}.row{display:none;gap:8px}.row button{flex:1}
.lock .inp{pointer-events:none;opacity:.55}.lock #go{display:none}.lock .row{display:flex}</style></head><body>${inner}${SCRIPT}</body></html>`,
{ status, headers: { "content-type": "text/html; charset=utf-8" } });

async function read(gh, config, number) {
  const [o, n] = config.tasks.split("/");
  const r = await gh.gql(`query($o:String!,$n:String!,$i:Int!){repository(owner:$o,name:$n){labels(first:100){nodes{name}}
    issue(number:$i){id title url body labels(first:50){nodes{name}} comments(last:40){nodes{body bodyHTML url createdAt author{login}}}}}}`, { o, n, i: number });
  const { issue, labels } = r.repository;
  const comments = issue.comments.nodes;
  const question = latestQuestion(comments.map((c) => c.body));
  const asked = comments.findLast((c) => /^## 問い/.test(norm(c.body)));
  return { issue, comments, asked, question, all: labels.nodes.map((l) => l.name), have: issue.labels.nodes.map((l) => l.name) };
}

const seg = (name, values) => `<div class="seg">${values.map((v, i) => `<label><input type="radio" name="${name}" value="${esc(v)}"${i ? "" : " checked"}>${esc(v)}</label>`).join("")}</div>`;
const box = (type, name, value, text, extra = "", cls = "opt") => `<label class="${cls}"><input type="${type}" name="${name}" value="${esc(value)}"${extra}><span>${esc(text)}</span></label>`;
const fold = (title, inner, open = false) => (inner ? `<details${open ? " open" : ""}><summary>${title}</summary><div>${inner}</div></details>` : "");

// 問いの種類ごとの回答の欄。判断は案（無ければ補足だけ）、確かめは項目ごとに問題の有無、採否とイレギュラーは決まった選択肢。
function answerField(q, items) {
  if (q.kind === "判断") return q.plans.length ? `<p class="sec">回答</p>${[...q.plans, NONE].map((p) => box("radio", "choice", p, p)).join("")}` : "";
  if (q.kind === "確かめ") return `<p class="sec">項目ごとに</p>${items.map((t, i) => `<div class="item"><p>${esc(t)}</p>${seg(`ok${i}`, OK)}
    <input type="text" name="note${i}" placeholder="問題の内容" aria-label="問題の内容"></div>`).join("")}`;
  return `<p class="sec">回答</p>${seg("choice", CHOICES[q.kind])}`;
}

async function submit(gh, env, config, number, form) {
  const { issue, question: q, all, have } = await read(gh, config, number);
  if (!q || q.answer) return { error: "答えていない問いがありません。" };
  if (form.get("question") !== q.text) return { error: "問いが新しくなっています。開き直してください。" };
  const items = confirmItems(issue.body);
  const choice = form.get("choice");
  const chosen = form.getAll("label").filter((n) => all.includes(n));
  const added = chosen.filter((n) => !have.includes(n));
  const removed = have.filter((n) => all.includes(n) && !chosen.includes(n));
  const lines = ["## 回答", `**${q.text}**`, ""];
  if (choice) lines.push(`回答: ${choice}`);
  items.forEach((item, i) => lines.push(form.get(`ok${i}`) === OK[1] ? `- ${OK[1]}: ${item} — ${form.get(`note${i}`) || "（内容の記入なし）"}` : `- ${OK[0]}: ${item}`));
  if (added.length || removed.length) lines.push(`ラベル: ${[...added.map((n) => `+${n}`), ...removed.map((n) => `−${n}`)].join(" ")}`);
  if (String(form.get("note") ?? "").trim()) lines.push(`補足: ${String(form.get("note")).trim()}`);
  const user = new GitHub(env.FORM_TOKEN);
  const path = `/repos/${config.tasks}/issues/${number}`;
  await user.rest("POST", `${path}/comments`, { body: lines.join("\n") });
  await Promise.all([added.length && user.rest("POST", `${path}/labels`, { labels: added }),
    ...removed.map((n) => user.rest("DELETE", `${path}/labels/${encodeURIComponent(n)}`))].filter(Boolean));
  return { url: issue.url, label: choice || (q.kind === "確かめ" ? "確かめの結果" : "補足") };
}

export async function answerForm(request, env, config) {
  const number = Number(new URL(request.url).searchParams.get("issue"));
  const gh = await GitHub.app(env, config.installation);
  if (request.method === "POST") return Response.json(await submit(gh, env, config, number, await request.formData()));
  const { issue, comments, asked, question: q, all, have } = await read(gh, config, number);
  if (!q || q.answer) return page(`<p>#${number} に、答えていない問いはありません。</p>`, 404);
  const said = q.kind === "イレギュラー" ? comments.findLast((c) => /^### \S+担当の終わり/.test(norm(c.body)))?.bodyHTML : null;
  const recent = comments.filter((c) => c !== asked).slice(-RECENT).reverse()
    .map((c) => `<p class="note"><a href="${esc(c.url)}">${esc(c.author?.login ?? "ghost")} ・ ${when(c.createdAt)}</a></p>${c.bodyHTML}`).join("");
  // 判断材料と本文は GitHub の Markdown の描き方で HTML にする（tasks#102）。互いに独立なので並べて打つ。
  const md = (text) => (text ? gh.rest("POST", "/markdown", { text, mode: "gfm", context: config.tasks }) : "");
  const [material, body] = await Promise.all([md(q.material), md(bodyRest(issue.body).trim())]);
  return page(`<p class="num">#${number}</p><p class="title">${esc(issue.title)}</p><p>${esc(q.text)}</p>${said ? `<div>${said}</div>` : ""}
${fold("判断材料", material, true)}${fold("本文", body)}${fold("最近のコメント", recent)}
<form><input type="hidden" name="question" value="${esc(q.text)}"><div class="inp">${answerField(q, confirmItems(issue.body))}
<textarea name="note" rows="2" placeholder="補足（任意）" aria-label="補足"></textarea>
<details class="labels"><summary class="s">ラベル（任意）</summary><div>${all.map((n) => box("checkbox", "label", n, n, have.includes(n) ? " checked" : "", "")).join("")}</div></details>
</div><p id="err"></p><button type="button" id="go" class="sub">確認</button><div class="row"><button type="button" id="back" class="sub">戻る</button><button class="main">送信</button></div></form>`);
}
