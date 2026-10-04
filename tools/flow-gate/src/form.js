// 回答フォーム。回答待ちのときだけ開く。答えのコメントは hidakagit の名義（env.FORM_TOKEN）で書き、遷移はゲートが書く。
import { Gate } from "./gate.js";
import { GitHub } from "./github.js";
import { answerBody, bodyRest, checkAll, judge, nextChoices, normalize, parseQuestion, remaining } from "./rules.js";

const SCAN = 30; // 問いを探すために読むコメントの件数
const RECENT = 5; // 材料に載せる最近のコメントの件数
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// 1回目の送信で選んだ内容を見せ、2回目で送る。完了の条件のチェック欄は、完成を選んだときだけ出して必須にする。
const SCRIPT = `<script>
const f = document.querySelector("form"), left = document.getElementById("left");
const sync = () => { const on = f.next.value && f.querySelector("[name=next]:checked").dataset.complete === "1";
  if (left) { left.hidden = !on; left.querySelectorAll("input").forEach((b) => (b.required = on)); } };
f?.addEventListener("change", sync); f && sync();
f?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!f.classList.contains("confirm")) {
    document.getElementById("sum").textContent = "送る内容: " + [f.plan?.value, f.querySelector("[name=next]:checked").dataset.text, f.note.value && "補足あり"].filter(Boolean).join(" ／ ");
    return f.classList.add("confirm");
  }
  f.querySelectorAll("button").forEach((b) => (b.disabled = true));
  const j = await (await fetch(location.pathname, { method: "POST", body: new FormData(f) })).json();
  document.body.innerHTML = "";
  document.body.append(Object.assign(document.createElement("p"), { textContent: j.error || "受け付けました（" + j.label + "）。" }));
  if (j.url) document.body.append(Object.assign(document.createElement("a"), { href: j.url, textContent: "GitHub に戻る", className: "back" }));
});
document.getElementById("back")?.addEventListener("click", () => f.classList.remove("confirm"));
</script>`;

const page = (body, status = 200) =>
  new Response(
    `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">` +
      `<title>回答</title><style>body{font:15px/1.5 system-ui,sans-serif;max-width:34rem;margin:.6rem auto;padding:0 16px}h1{font-size:1.05rem}h2{font-size:.95rem;margin:.9rem 0 .2rem}` +
      `details{border:1px solid #8884;border-radius:.4rem;padding:.4rem .6rem;margin:.5rem 0;overflow-wrap:anywhere}details>div{max-height:40vh;overflow:auto}` +
      `label{display:flex;gap:.5rem;padding:.45rem .6rem;border:1px solid #8886;border-radius:.4rem;margin:.3rem 0}textarea{width:100%;box-sizing:border-box;font:inherit}` +
      `button,.back{display:block;width:100%;padding:.6rem;margin-top:.4rem;border-radius:.4rem;border:0;background:#1f6feb;color:#fff;font:inherit;text-align:center;text-decoration:none}` +
      `.ok,#sum{display:none}.confirm .ok,.confirm #sum{display:block}.confirm .ask{display:none}.confirm label{pointer-events:none;opacity:.6}.who{font-size:13px}` +
      `</style></head><body>${body}${SCRIPT}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );

// 回答待ちのタスクと、最新の「## 問い」のコメントを読む。答えられなければ理由を返す。
async function load(gate, number) {
  const issue = await gate.read({ number }, { comments: SCAN });
  if (!issue?.item) return { error: "この issue は対象外です。" };
  if (issue.state !== "OPEN" || issue.status !== gate.config.waiting) return { error: `いまは回答待ちではありません（${issue.state === "OPEN" ? issue.status : "閉じています"}）。` };
  const asked = issue.comments.nodes.findLast((c) => normalize(c.body).startsWith("## 問い\n"));
  const question = asked && parseQuestion(asked.body);
  if (!question) return { error: "問いのコメントが見つかりません。issue を開いて確かめてください。" };
  return { issue, asked, question, labels: Object.keys(gate.labelIds), choices: nextChoices(gate.config, issue.status), left: remaining(issue.body) };
}

function render({ issue, asked, question, labels, choices, left, html }) {
  const fold = (title, inner, open = false) => `<details${open ? " open" : ""}><summary>${title}</summary><div>${inner}</div></details>`;
  const md = (h, text) => h ?? `<div style="white-space:pre-wrap">${esc(text)}</div>`;
  const box = (type, name, value, text, extra = "") => `<label><input type="${type}" name="${name}" value="${esc(value)}"${extra}> ${esc(text)}</label>`;
  const when = (t) => new Date(Date.parse(t) + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
  const recent = issue.comments.nodes.slice(-RECENT).reverse().map((c) => `<p class="who"><a href="${esc(c.url)}">${esc(c.author?.login ?? "ghost")} ・ ${when(c.createdAt)}</a></p>${c.bodyHTML}`);
  const have = new Set(issue.labels.nodes.map((l) => l.name));
  return page(
    `<h1>#${issue.number} ${esc(issue.title)}</h1><p>${esc(question.text)}</p>` +
      (question.material ? fold("判断材料", md(html.material, question.material), true) : "") +
      (bodyRest(issue.body).trim() ? fold("本文", md(html.body, bodyRest(issue.body).trim())) : "") +
      fold("最近のコメント（新しい順）", recent.join("")) +
      `<a href="${esc(issue.url)}">issue を開く</a><form><input type="hidden" name="issue" value="${issue.number}"><input type="hidden" name="q" value="${esc(asked.url)}">` +
      (question.plans.length ? `<h2>回答</h2>${question.plans.map((p) => box("radio", "plan", p, p)).join("")}` : "") +
      `<textarea name="note" rows="4" placeholder="補足（任意）"></textarea>` +
      `<h2>次のステータス</h2>${choices.map((c, i) => box("radio", "next", i, c.text, ` required data-text="${esc(c.text)}"${c.close === "COMPLETED" ? ' data-complete="1"' : ""}${i ? "" : " checked"}`)).join("")}` +
      (left.length ? `<div id="left" hidden><h2>確かめた完了の条件</h2>${left.map((l) => box("checkbox", "done", l, l)).join("")}</div>` : "") +
      fold("ラベル", labels.map((n) => box("checkbox", "label", n, n, have.has(n) ? " checked" : "")).join("")) +
      `<p id="sum"></p><button type="button" id="back" class="ok">戻る</button><button class="ok">送信</button><button class="ask">確認へ</button></form>`,
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
  const answer = { question, plan: question.plans.find((p) => p === data.get("plan")), choice, checked,
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
  const draw = (text) => (text ? gate.gh.markdown(text, config.repository).catch(() => null) : null);
  const [material, body] = await Promise.all([draw(loaded.question.material), draw(bodyRest(loaded.issue.body).trim())]);
  return render({ ...loaded, html: { material, body } });
}
