// 回答フォーム。回答待ちのときだけ開く。答えのコメントは hidakagit の名義（env.FORM_TOKEN）で書き、遷移はゲートが書く。
import { Gate } from "./gate.js";
import { GitHub } from "./github.js";
import { answerBody, bodyRest, checkAll, judge, nextChoices, normalize, parseQuestion, remaining } from "./rules.js";

const RECENT = 5; // 材料に載せる最近のコメントの件数（上に出した問いのコメントは数えない）
// 案のどれでもないときの答え（補足に進め方を書く）。案のある問いでだけ、案の最後に並べる。
const NONE = "どれでもない（補足に書く）";
const plansOf = (question) => [...question.plans, NONE];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// 「確認へ」で入力を固め（完成なのに条件が残っていれば止める）、「送信」で送る。送ったあとは結果と「GitHub に戻る」だけ。
const SCRIPT = `<script>
const f = document.querySelector("form"), left = document.getElementById("left"), err = document.getElementById("err");
const sync = () => { if (left) left.hidden = f.querySelector("[name=next]:checked").dataset.complete !== "1"; err.textContent = ""; };
f?.addEventListener("change", sync); f && sync();
document.getElementById("go")?.addEventListener("click", () => {
  if (left && !left.hidden && [...left.querySelectorAll("input")].some((b) => !b.checked)) return (err.textContent = "完了の条件が残っています");
  f.classList.add("lock");
});
document.getElementById("back")?.addEventListener("click", () => f.classList.remove("lock"));
f?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!f.classList.contains("lock")) return;
  f.querySelectorAll("button").forEach((b) => (b.disabled = true));
  const j = await (await fetch(location.pathname, { method: "POST", body: new FormData(f) })).json();
  const p = (text, className = "") => Object.assign(document.createElement("p"), { textContent: text, className });
  document.body.replaceChildren(p(j.error || "受け付けました（" + j.label + "）。"));
  if (!j.url) return;
  // 先にタブを閉じる（リンクで移ったあとではこのページが無く、閉じる処理が動かない）。閉じられない開き方なら issue へ移る。
  const back = Object.assign(document.createElement("button"), { textContent: "GitHub に戻る", className: "sub" });
  back.addEventListener("click", () => (window.close(), setTimeout(() => location.replace(j.url), 300)));
  document.body.append(back, p("押すとこのタブを閉じる。閉じられない開き方のときは issue へ移る。", "note"));
});
</script>`;

// 見た目は合意したモック（スマホの幅で1列。材料と選ぶ行は下の区切り線だけ、次のステータスは1行のボタン）。
const page = (body, status = 200) =>
  new Response(
    `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">` +
      `<title>回答</title><style>body{font:14px/1.6 system-ui,sans-serif;max-width:34rem;margin:.75rem auto;padding:0 16px}p{margin:0 0 .5rem}` +
      `.num,.sec,.note,summary.s{font-size:13px;opacity:.7}.num{font-size:12px;margin:0}.title{font-weight:500;margin:0 0 6px}.sec{margin:14px 0 6px}` +
      `details{border-bottom:1px solid #8884;padding:6px 0;overflow-wrap:anywhere}details>div{max-height:40vh;overflow:auto;font-size:13px;margin-top:6px}` +
      `.opt{display:flex;gap:8px;align-items:flex-start;padding:7px 0;border-bottom:1px solid #8884;overflow-wrap:anywhere}.cond .opt{font-size:13px}` +
      `textarea{width:100%;box-sizing:border-box;font:inherit;margin-top:8px}` +
      `.seg{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;border:1px solid #8888;border-radius:8px;overflow:hidden}` +
      `.seg label{text-align:center;font-size:13px;padding:8px 0}.seg label+label{border-left:1px solid #8888}.seg input{position:absolute;opacity:0;pointer-events:none}` +
      `.seg label:has(input:checked){background:#1f6feb22;color:#1f6feb}.labels{border:0;margin-top:6px}.labels>div{display:flex;flex-wrap:wrap;gap:10px}` +
      `#err{font-size:13px;color:#d1242f;min-height:1em;margin:8px 0 0}button{display:block;width:100%;padding:8px;margin-top:4px;border-radius:8px;font:inherit}` +
      `.sub{background:transparent;color:inherit;border:1px solid #8888}.main{background:#1f6feb;color:#fff;border:0}.row{display:none;gap:8px}.row button{flex:1}` +
      `.lock .inp{pointer-events:none;opacity:.55}.lock #go{display:none}.lock .row{display:flex}` +
      `</style></head><body>${body}${SCRIPT}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );

// 回答待ちのタスクと、最新の「## 問い」のコメントを読む。答えられなければ理由を返す。
async function load(gate, number) {
  const issue = await gate.read({ number });
  if (!issue?.item) return { error: "この issue は対象外です。" };
  if (issue.state !== "OPEN" || issue.status !== gate.config.waiting) return { error: `いまは回答待ちではありません（${issue.state === "OPEN" ? issue.status : "閉じています"}）。` };
  const asked = issue.comments.nodes.findLast((c) => normalize(c.body).startsWith("## 問い\n"));
  const question = asked && parseQuestion(asked.body);
  if (!question) return { error: "問いのコメントが見つかりません。issue を開いて確かめてください。" };
  return { issue, asked, question, labels: Object.keys(gate.labelIds), choices: nextChoices(gate.config, issue.status), left: remaining(issue.body) };
}

function render({ issue, asked, question, labels, choices, left, html }) {
  const fold = (title, inner, open = false) => `<details${open ? " open" : ""}><summary>${title}</summary><div>${inner}</div></details>`;
  const box = (type, name, value, text, extra = "", cls = "opt") => `<label class="${cls}"><input type="${type}" name="${name}" value="${esc(value)}"${extra}><span>${esc(text)}</span></label>`;
  const when = (t) => new Date(Date.parse(t) + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
  const recent = issue.comments.nodes.filter((c) => c !== asked).slice(-RECENT).reverse().map((c) => `<p class="note"><a href="${esc(c.url)}">${esc(c.author?.login ?? "ghost")} ・ ${when(c.createdAt)}</a></p>${c.bodyHTML}`);
  const have = new Set(issue.labels.nodes.map((l) => l.name));
  return page(
    `<p class="num">#${issue.number}</p><p class="title">${esc(issue.title)}</p><p>${esc(question.text)}</p>` +
      (html.material ? fold("判断材料", html.material, true) : "") +
      (html.body ? fold("本文", html.body) : "") +
      fold("最近のコメント", recent.join("")) +
      `<form><input type="hidden" name="issue" value="${issue.number}"><input type="hidden" name="q" value="${esc(asked.url)}"><div class="inp">` +
      (question.plans.length ? `<p class="sec">回答</p>${plansOf(question).map((p) => box("radio", "plan", p, p)).join("")}` : "") +
      `<textarea name="note" rows="2" placeholder="補足（任意）"></textarea>` +
      `<p class="sec">次のステータス</p><div class="seg">${choices.map((c, i) => box("radio", "next", i, c.text, ` data-text="${esc(c.text)}"${c.close === "COMPLETED" ? ' data-complete="1"' : ""}${i ? "" : " checked"}`, "")).join("")}</div>` +
      (left.length ? `<div id="left" class="cond" hidden><p class="sec">残っている完了の条件（確かめたものにチェック）</p>${left.map((l) => box("checkbox", "done", l, l)).join("")}</div>` : "") +
      `<details class="labels"><summary class="s">ラベル（任意）</summary><div>${labels.map((n) => box("checkbox", "label", n, n, have.has(n) ? " checked" : "", "")).join("")}</div></details>` +
      `</div><p id="err"></p><button type="button" id="go" class="sub">確認へ</button><div class="row"><button type="button" id="back" class="sub">戻る</button><button class="main">送信</button></div></form>`,
  );
}

async function submit(gate, env, data) {
  const loaded = await load(gate, Number(data.get("issue")));
  if (loaded.error) return loaded;
  const { issue, asked, question, labels, choices, left } = loaded;
  if (data.get("q") !== asked.url) return { error: "問いが新しくなっています。開き直してください。" };
  const choice = choices[Number(data.get("next"))];
  if (!choice) return { error: "次のステータスを1つ選んでください。" };
  const had = issue.labels.nodes.map((l) => l.name).filter((n) => labels.includes(n));
  const chosen = data.getAll("label").filter((n) => labels.includes(n));
  const checked = choice.close === "COMPLETED" ? data.getAll("done").filter((d) => left.includes(d)) : [];
  const body = checked.length && checked.length === left.length ? checkAll(issue.body) : undefined;
  // 断る答えは記録も書かないので、先に照らす（書くのは gate.apply で、同じ照らし）。
  const verdict = judge(gate.config, issue.status, choice.to, { close: choice.close, body: body ?? issue.body });
  if (!verdict.ok) return { error: verdict.reason };
  const answer = { question, plan: plansOf(question).find((p) => p === data.get("plan")), choice, checked,
    added: chosen.filter((n) => !had.includes(n)), removed: had.filter((n) => !chosen.includes(n)), note: String(data.get("note") ?? "").trim() };
  await new GitHub(env.FORM_TOKEN).write([["addComment", { subjectId: issue.id, body: answerBody(answer) }]]);
  await gate.apply(issue, choice.to, { close: choice.close, body, labels: answer.added, unlabels: answer.removed });
  return { url: issue.url, label: choice.text };
}

export async function answerForm(request, env, config) {
  const gate = await Gate.open(env, config);
  if (request.method === "POST") return Response.json(await submit(gate, env, await request.formData()));
  const loaded = await load(gate, Number(new URL(request.url).searchParams.get("issue")));
  if (loaded.error) return page(`<p>${esc(loaded.error)}</p>`, 404);
  // 判断材料と本文は GitHub の Markdown の描き方で HTML にする。
  const draw = (text) => (text ? gate.gh.markdown(text, config.repository) : null);
  const [material, body] = await Promise.all([draw(loaded.question.material), draw(bodyRest(loaded.issue.body).trim())]);
  return render({ ...loaded, html: { material, body } });
}
