// 回答フォーム（ユーザーが開く1枚の画面）。答えのコメントは hidakagit の名義（env.FORM_TOKEN）で書き、
// ステータス・ラベルはゲートの遷移の処理（Gate.apply）がゲートの名義で書く（担当者はステータスから決まる）。
import { Gate, currentQuestion } from "./gate.js";
import { GitHub, Mutations } from "./github.js";
import { answerBody, answerChoices, splitBody, userTurn } from "./rules.js";

// 材料に載せる最近のコメントの件数。保留の理由・確かめる担当の結果・前の答えは、どれも最近のコメントにある。
const RECENT = 5;

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// 送信は fetch で行い、ページを移らない（履歴が1ページのタブだけがスクリプトで閉じられる）。
// 1回目の送信で選んだ内容を見せ、2回目で送る。
const SCRIPT = `<script>
const f = document.querySelector("form"), sum = document.getElementById("sum");
if (matchMedia("(min-width:960px)").matches) document.querySelectorAll(".mats>details").forEach((d) => (d.open = true));
f?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!f.classList.contains("confirm")) {
    const c = f.querySelector("[name=choice]:checked");
    const ch = [...f.querySelectorAll("[name=label]")].filter((b) => b.checked !== Boolean(b.dataset.had)).map((b) => (b.checked ? "+" : "−") + b.value);
    sum.textContent = "送る内容: " + c.dataset.text +
      (ch.length ? " ／ ラベル " + ch.join(" ") : "") + (f.note.value ? " ／ 補足あり" : "");
    f.classList.add("confirm");
    return;
  }
  const data = new FormData(f);
  f.querySelectorAll("button").forEach((b) => (b.disabled = true));
  sum.textContent = "送信しています…";
  const r = await fetch(location.pathname, { method: "POST", body: data });
  const j = await r.json();
  document.body.textContent = "";
  const p = document.createElement("p");
  p.textContent = j.error || "受け付けました（" + j.label + "）。";
  document.body.append(p);
  if (j.url) {
    // 先にタブを閉じる（リンクで移ったあとではこのページが無く、閉じる処理が動かない）。ブラウザが閉じさせない開き方
    // （移動したことのあるタブなど）なら、issue へ移る。
    const a = document.createElement("a");
    a.href = j.url; a.textContent = "GitHub に戻る"; a.className = "back";
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      window.close();
      setTimeout(() => location.replace(j.url), 300);
    });
    document.body.append(a);
  }
});
document.getElementById("back")?.addEventListener("click", () => f.classList.remove("confirm"));
</script>`;

const page = (body, status = 200) =>
  new Response(
    `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
      `<meta name="color-scheme" content="light dark"><title>回答</title><style>` +
      `body{font:15px/1.5 system-ui,sans-serif;max-width:34rem;margin:.6rem auto;padding:0 16px}` +
      `h1{font-size:1.05rem;margin:.2rem 0}p{margin:.4rem 0}` +
      `.mats>details{background:#f4f4f4;padding:.4rem .6rem;border-radius:.4rem;font-size:14px;margin:.5rem 0}.mats>details>div{overflow-wrap:anywhere;max-height:32vh;overflow:auto}` +
      `.c+.c{border-top:1px solid #ccc;margin-top:.4rem}.who{font-size:13px;margin:.3rem 0 0}.who a{color:inherit}.open{display:block;margin:.6rem 0}` +
      `.plain{white-space:pre-wrap}.md p,.md ul,.md ol{margin:.3rem 0}.md ul,.md ol{padding-left:1.2rem}.md a{color:#1f6feb}` +
      `.md code{font-size:13px;background:rgba(127,127,127,.15);padding:0 .2em;border-radius:3px}` +
      `label{display:flex;gap:.5rem;align-items:center;padding:.45rem .6rem;border:1px solid #bbb;border-radius:.4rem;margin:.3rem 0}` +
      `textarea,select{width:100%;box-sizing:border-box;font:inherit;font-size:14px}` +
      `.row{display:flex;gap:.5rem;margin-top:.4rem}.row button{flex:1;font:inherit;padding:.6rem;border-radius:.4rem;border:1px solid #888}` +
      `.primary{background:#1f6feb;color:#fff;border-color:#1f6feb!important}button:disabled{opacity:.5}` +
      `.ok,#sum{display:none}.confirm .ok,.confirm #sum{display:block}.confirm .ask{display:none}.confirm label{pointer-events:none;opacity:.6}` +
      `.labels{display:flex;flex-wrap:wrap;gap:.3rem}.labels label{margin:0;padding:.3rem .55rem;font-size:14px}` +
      `.back{display:block;text-align:center;padding:.7rem;border-radius:.4rem;background:#1f6feb;color:#fff;text-decoration:none;margin-top:.6rem}` +
      `@media(prefers-color-scheme:dark){body{background:#121212;color:#eee}.mats>details{background:#222}label{border-color:#444}.c+.c{border-color:#444}}` +
      // 狭い幅では選択肢と送信を材料より先に置く（答える操作がいつも最初に見える）。PC の幅では、材料を左に開いたまま全部、
      // 選択肢と送信を右に並べ、右はスクロールしても見える位置に留める。
      `@media(min-width:960px){body{max-width:72rem}.cols{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:1.5rem;align-items:start}` +
      `.mats{grid-column:1;grid-row:1}.mats>details:first-child{margin-top:0}.mats>details>div{max-height:none}.cols form{grid-column:2;grid-row:1;position:sticky;top:.6rem}}` +
      `</style></head><body>${body}${SCRIPT}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );

// 今の問いと、答えてよいか（ユーザーの番か）を読む。答えられなければ理由を返す。
// ラベルはユーザーが付けるもので、置き場のリポジトリに GitHub で定義されているものを名前を持たずに全部出す。
// Project の欄（優先度・規模など）は機械が決めるので出さない。
async function load(gate, number, options) {
  const issue = await gate.read({ number }, options);
  if (!issue?.item) return { error: "この issue は対象外です。" };
  if (!userTurn(gate.config, issue)) return { error: `いまはあなたの番ではありません（${issue.state === "OPEN" ? `ステータス: ${issue.status ?? "無し"}` : "閉じています"}）。` };
  const q = currentQuestion(gate.config, issue);
  const labels = Object.keys(gate.labelIds);
  return { issue, q, labels, choices: answerChoices(gate.config, q.parsed, issue.status) };
}

// 材料は、どの問いでも同じものを出す: 問いの判断材料（あれば最初から開く）・本文（ゲートの印の間を除く）・最近のコメント（新しいものが上）。
// html は GitHub が描いた判断材料と本文。描けなかったもの（null）は文字をそのまま出す。
function render(config, { issue, q, labels, choices, html }) {
  const have = new Set(issue.labels.nodes.map((l) => l.name));
  const boxes = labels.map(
    (n) => `<label><input type="checkbox" name="label" value="${esc(n)}"${have.has(n) ? ' checked data-had="1"' : ""}> ${esc(n)}</label>`,
  );
  const radios = choices.map(
    (c, i) =>
      `<label><input type="radio" name="choice" value="${i}" required data-text="${esc(c.text)}"> ${esc(c.text)}</label>`,
  );
  const md = (h, text) => (h != null ? `<div class="md">${h}</div>` : `<div class="plain">${esc(text)}</div>`);
  const fold = (title, inner, open = false) => `<details${open ? " open" : ""}><summary>${title}</summary>${inner}</details>`;
  const when = (t) => new Date(Date.parse(t) + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
  const comments = [...issue.comments.nodes].reverse().map(
    (c) => `<section class="c"><p class="who"><a href="${esc(c.url)}">${esc(c.author?.login ?? "ghost")} ・ ${when(c.createdAt)}</a></p><div class="md">${c.bodyHTML}</div></section>`,
  );
  const rest = splitBody(issue.body).rest.trim();
  const mats =
    (q.parsed.material ? fold("判断材料", md(html.material, q.parsed.material), true) : "") +
    (rest ? fold("本文", md(html.body, rest)) : "") +
    (comments.length ? fold("最近のコメント（新しい順）", `<div>${comments.join("")}</div>`) : "") +
    `<a class="open" href="${esc(issue.url)}">issue を開く</a>`;
  return page(
    `<h1>#${issue.number} ${esc(issue.title)}</h1><p>${esc(q.parsed.text)}</p><div class="cols">` +
      `<form><input type="hidden" name="issue" value="${issue.number}"><input type="hidden" name="q" value="${esc(q.id)}">${radios.join("")}` +
      `<p>ラベル</p><div class="labels">${boxes.join("")}</div>` +
      `<p><textarea name="note" rows="6" placeholder="補足（選択肢に「補足」とあるものを選んだときは必須）"></textarea></p>` +
      `<p id="sum"></p><div class="row"><button type="button" id="back" class="ok">戻る</button><button class="ok primary">送信</button>` +
      `<button class="ask primary">確認へ</button></div></form><div class="mats">${mats}</div></div>`,
  );
}

async function submit(gate, env, data) {
  const loaded = await load(gate, Number(data.get("issue")));
  if (loaded.error) return loaded;
  const { issue, q, labels, choices } = loaded;
  if (data.get("q") !== q.id) return { error: "問いが新しくなっています。開き直してください。" };
  const choice = choices[Number(data.get("choice"))];
  const note = String(data.get("note") ?? "").trim();
  if (!choice) return { error: "選択肢を1つ選んでください。" };
  if (choice.note && !note) return { error: `「${choice.text}」には補足が要ります。` };
  const had = issue.labels.nodes.map((l) => l.name).filter((n) => labels.includes(n));
  const chosen = data.getAll("label").map(String).filter((n) => labels.includes(n));
  const added = chosen.filter((n) => !had.includes(n));
  const removed = had.filter((n) => !chosen.includes(n));
  const want = { close: choice.close, labels: added, unlabels: removed, clearQuestion: true };
  const precheck = await gate.apply(issue, choice.to, { ...want, dryRun: true });
  if (!precheck.ok) return { error: precheck.reason };

  // 答えの記録（ユーザーの名義）を先に書き、決定と見せ方（ゲートの名義。本文の問いとボタンを消す）を書いてから返す。
  const body = answerBody({ question: q.parsed, choices, choice, note, added, removed });
  await new Mutations().add("addComment", { subjectId: issue.id, body }).send(new GitHub(env.FORM_TOKEN));
  const r = await gate.apply(issue, choice.to, want);
  if (!r.ok) return { error: r.reason };
  return { url: issue.url, label: choice.text };
}

export async function answerForm(request, env, config) {
  const url = new URL(request.url);
  const gate = await Gate.open(env, config);
  if (request.method === "POST") return Response.json(await submit(gate, env, await request.formData()));
  const loaded = await load(gate, Number(url.searchParams.get("issue")), { comments: RECENT });
  if (loaded.error) return page(`<p>${esc(loaded.error)}</p>`, 404);
  // 本文は印の間（ボタンと問い）を除いてから描くので、GitHub が描いた bodyHTML は使えない。
  const draw = (name, text) =>
    text ? gate.gh.markdown(text, config.repository).catch((e) => (console.warn(`${name}を描けなかった: ${e.message}`), null)) : null;
  const [material, body] = await Promise.all([draw("判断材料", loaded.q.parsed.material), draw("本文", splitBody(loaded.issue.body).rest.trim())]);
  return render(config, { ...loaded, html: { material, body } });
}
