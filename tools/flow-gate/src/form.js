// 回答フォーム（hidakagit が開く1枚の画面）。答えのコメントは hidakagit の名義（env.FORM_TOKEN）で書き、
// ステータス・割り当て・ラベルはゲートの遷移の処理（Gate.apply）がゲートの名義で書く。
import { Gate, currentQuestion } from "./gate.js";
import { GitHub, Mutations } from "./github.js";
import { answerBody, formChoices } from "./rules.js";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// 送信は fetch で行い、ページを移らない（履歴が1ページのタブだけがスクリプトで閉じられる）。
// 1回目の送信で選んだ内容を見せ、2回目で送る。
const SCRIPT = `<script>
const f = document.querySelector("form"), sum = document.getElementById("sum");
f?.addEventListener("change", (e) => {
  if (e.target.name === "choice") f.next.value = e.target.dataset.next || "";
  document.getElementById("who").hidden = !e.target.form.querySelector("[name=choice]:checked")?.dataset.next;
});
f?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!f.classList.contains("confirm")) {
    const c = f.querySelector("[name=choice]:checked");
    const ch = [...f.querySelectorAll("[name=label]")].filter((b) => b.checked !== Boolean(b.dataset.had)).map((b) => (b.checked ? "+" : "−") + b.value);
    sum.textContent = "送る内容: " + c.dataset.text + (c.dataset.next ? " ／ 次に動くのは " + f.next.selectedOptions[0].text : "") +
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
    const a = document.createElement("a");
    a.href = j.url; a.textContent = "GitHub に戻る"; a.className = "back";
    a.addEventListener("click", () => setTimeout(() => window.close(), 400));
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
      `details{background:#f4f4f4;padding:.4rem .6rem;border-radius:.4rem;font-size:14px}details div{white-space:pre-wrap;overflow-wrap:anywhere;max-height:32vh;overflow:auto}` +
      `label{display:flex;gap:.5rem;align-items:center;padding:.45rem .6rem;border:1px solid #bbb;border-radius:.4rem;margin:.3rem 0}` +
      `textarea,select{width:100%;box-sizing:border-box;font:inherit;font-size:14px}` +
      `.row{display:flex;gap:.5rem;margin-top:.4rem}.row button{flex:1;font:inherit;padding:.6rem;border-radius:.4rem;border:1px solid #888}` +
      `.primary{background:#1f6feb;color:#fff;border-color:#1f6feb!important}button:disabled{opacity:.5}` +
      `.ok,#sum{display:none}.confirm .ok,.confirm #sum{display:block}.confirm .ask{display:none}.confirm label{pointer-events:none;opacity:.6}` +
      `.labels{display:flex;flex-wrap:wrap;gap:.3rem}.labels label{margin:0;padding:.3rem .55rem;font-size:14px}` +
      `.back{display:block;text-align:center;padding:.7rem;border-radius:.4rem;background:#1f6feb;color:#fff;text-decoration:none;margin-top:.6rem}` +
      `@media(prefers-color-scheme:dark){body{background:#121212;color:#eee}details{background:#222}label{border-color:#444}}` +
      `</style></head><body>${body}${SCRIPT}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );

// 今の問いと、答えてよいか（答える人の番か）を読む。答えられなければ理由を返す。
// ラベルはユーザーが付けるもので、置き場のリポジトリに GitHub で定義されているものを名前を持たずに全部出す。
// Project の欄（優先度・規模など）は機械が決めるので出さない。
async function load(gate, number) {
  const issue = await gate.read({ number });
  if (!issue?.item) return { error: "この issue は対象外です。" };
  if (!gate.config.ask.statuses.includes(issue.status)) return { error: `いまは答える問いがありません（ステータス: ${issue.status ?? "無し"}）。` };
  const answerer = gate.config.people[gate.config.ask.answerer].node;
  if (!issue.assignees.nodes.some((a) => a.id === answerer)) return { error: "いまは Claude の番です（答えは届いています）。" };
  const q = currentQuestion(gate.config, issue);
  if (!q) return { error: "答える問いがありません。" };
  if (!q.parsed) return { error: "問いの形が崩れています。Claude が書き直すのを待ってください。" };
  const labels = Object.keys(gate.labelIds);
  return { issue, q, labels, choices: formChoices(gate.config, q.parsed, issue.status) };
}

function render(config, { issue, q, labels, choices }) {
  const have = new Set(issue.labels.nodes.map((l) => l.name));
  const boxes = labels.map(
    (n) => `<label><input type="checkbox" name="label" value="${esc(n)}"${have.has(n) ? ' checked data-had="1"' : ""}> ${esc(n)}</label>`,
  );
  const people = Object.entries(config.people).map(([k, p]) => `<option value="${esc(k)}">${esc(p.shown)}</option>`);
  const radios = choices.map(
    (c, i) =>
      `<label><input type="radio" name="choice" value="${i}" required data-text="${esc(c.text)}" data-next="${esc(c.fixed ? "" : (c.next ?? ""))}"> ${esc(c.text)}</label>`,
  );
  return page(
    `<h1>#${issue.number} ${esc(issue.title)}</h1><p>${esc(q.parsed.text)}</p>` +
      (q.parsed.material ? `<details><summary>判断材料</summary><div>${esc(q.parsed.material)}</div></details>` : "") +
      `<form><input type="hidden" name="issue" value="${issue.number}"><input type="hidden" name="q" value="${esc(q.id)}">${radios.join("")}` +
      `<p id="who" hidden>次に動くのは <select name="next">${people.join("")}</select></p>` +
      `<p>ラベル</p><div class="labels">${boxes.join("")}</div>` +
      `<p><textarea name="note" rows="2" placeholder="補足（「その他」を選んだときは必須）"></textarea></p>` +
      `<p id="sum"></p><div class="row"><button type="button" id="back" class="ok">戻る</button><button class="ok primary">送信</button>` +
      `<button class="ask primary">確認へ</button></div></form>`,
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
  const next = choice.next === null ? null : choice.fixed ? choice.next : String(data.get("next"));
  if (next !== null && !gate.config.people[next]) return { error: "次に動く者が選べていません。" };
  const had = issue.labels.nodes.map((l) => l.name).filter((n) => labels.includes(n));
  const chosen = data.getAll("label").map(String).filter((n) => labels.includes(n));
  const added = chosen.filter((n) => !had.includes(n));
  const removed = had.filter((n) => !chosen.includes(n));
  const precheck = await gate.apply({ ...issue }, issue.status, choice.to, { dryRun: true });
  if (!precheck.ok) return { error: precheck.reason };

  // 答えの記録（hidakagit の名義）を先に書き、決定と見せ方（ゲートの名義。本文の問いとボタンを消す）を書いてから返す。
  const body = answerBody(gate.config, { question: q.parsed, choices, choice, next, note, added, removed });
  await new Mutations().add("addComment", { subjectId: issue.id, body }).send(new GitHub(env.FORM_TOKEN));
  const r = await gate.apply(issue, issue.status, choice.to, { next: next ?? undefined, labels: added, unlabels: removed, clearQuestion: true });
  if (!r.ok) return { error: r.reason };
  return { url: issue.url, label: choice.text };
}

export async function answerForm(request, env, config) {
  const url = new URL(request.url);
  const gate = await Gate.open(env, config, url.origin);
  if (request.method === "POST") return Response.json(await submit(gate, env, await request.formData()));
  const loaded = await load(gate, Number(url.searchParams.get("issue")));
  return loaded.error ? page(`<p>${esc(loaded.error)}</p>`, 404) : render(config, loaded);
}
