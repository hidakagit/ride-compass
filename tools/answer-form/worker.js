// 問いへの回答ページ。規約は docs/conventions/flow.md「回答ページ」。
// 問い（issue の最後の問いのコメント、または from=body なら issue の本文）の機械で読む部分に書かれた操作だけを出し、
// 答えを「種別・問い・選んだもの・本文」の行で issue のコメントに書く。受け取るかの判定は道具（scripts/flow.py）がする。
// 書く先は env.TASKS_REPO の issue だけ。秘密の値 env.GITHUB_TOKEN はそのリポジトリの Issues の読み書きだけを持つ。
const BLOCK = /<!-- flow\n種類: (\S+)\n([\s\S]*?)-->/;
const OP = /^操作: (.+?) \| (.+?) \| (.*)$/gm;
const QUERY =
  "query($o: String!, $n: String!, $k: Int!) { repository(owner: $o, name: $n) {" +
  " issue(number: $k) { title body comments(last: 30) { nodes { databaseId body } } } } }";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const html = (body, status = 200) =>
  new Response(
    `<!doctype html><html lang="ja"><head><meta charset="utf-8">` +
      `<meta name="viewport" content="width=device-width,initial-scale=1"><title>回答</title><style>` +
      `body{font:17px/1.6 system-ui,sans-serif;max-width:34rem;margin:1rem auto;padding:0 16px}` +
      `.m{white-space:pre-wrap;background:#f4f4f4;padding:.8rem;border-radius:.5rem;overflow-wrap:anywhere}` +
      `label{display:block;padding:.8rem;border:1px solid #bbb;border-radius:.5rem;margin:.5rem 0}` +
      `textarea{width:100%;box-sizing:border-box;font:inherit}button{font:inherit;padding:.7rem 1.6rem;margin:.3rem}` +
      `.e{color:#b00020}@media(prefers-color-scheme:dark){body{background:#121212;color:#eee}.m{background:#222}}` +
      `</style></head><body>${body}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );

function github(env, path, init = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "ride-compass-answer-form",
    },
  });
}

// 問い（種類・問いの番号・判断材料・選べる操作）。無ければ null。
async function question(env, issue, fromBody) {
  const [o, n] = env.TASKS_REPO.split("/");
  const res = await github(env, "/graphql", {
    method: "POST",
    body: JSON.stringify({ query: QUERY, variables: { o, n, k: Number(issue) } }),
  });
  const found = res.ok ? (await res.json()).data?.repository?.issue : null;
  if (!found) return null;
  const asked = fromBody
    ? { id: `#${issue}-本文`, body: found.body ?? "" }
    : [...found.comments.nodes]
        .reverse()
        .filter((c) => BLOCK.test(c.body))
        .map((c) => ({ id: `#${issue}-c${c.databaseId}`, body: c.body }))[0];
  const block = asked && BLOCK.exec(asked.body);
  if (!block) return null;
  const ops = [...block[2].matchAll(OP)].map(([, key, label, need]) => ({ key, label, need: need.trim() }));
  const material = asked.body
    .replace(BLOCK, "")
    .replace(/^(答える|中止する): \S+$/gm, "")
    .trim();
  return { issue, fromBody, title: found.title, kind: block[1], id: asked.id, ops, material };
}

// 全種類・全段（入力・確認・受付）の画面を組み立てる1つの関数。
function render(q, step, pick = "", text = "", error = "") {
  const op = q.ops.find((o) => o.key === pick);
  const hidden = (s) =>
    `<input type="hidden" name="issue" value="${esc(q.issue)}"><input type="hidden" name="from" value="${q.fromBody ? "body" : ""}">` +
    `<input type="hidden" name="step" value="${s}">`;
  const head = `<h1>${esc(q.title)}</h1><p>種別: ${esc(q.kind)}</p>`;
  if (step === "done") return html(`${head}<p>受け付けました（${esc(op.label)}）。</p>`);
  if (step === "confirm")
    return html(
      `${head}<p>この内容で送りますか？</p><p>選んだもの: ${esc(op.label)}</p>` +
        (text ? `<div class="m">${esc(text)}</div>` : "") +
        `<form method="post">${hidden("form")}<input type="hidden" name="pick" value="${esc(pick)}">` +
        `<input type="hidden" name="text" value="${esc(text)}"><button>戻る</button></form>` +
        `<form method="post">${hidden("send")}<input type="hidden" name="pick" value="${esc(pick)}">` +
        `<input type="hidden" name="text" value="${esc(text)}"><button>送信</button></form>`,
    );
  const radios = q.ops
    .map(
      (o) =>
        `<label><input type="radio" name="pick" value="${esc(o.key)}" required${o.key === pick ? " checked" : ""}> ` +
        `${esc(o.label)}${o.need ? `（${esc(o.need)}）` : ""}</label>`,
    )
    .join("");
  return html(
    `${head}${error ? `<p class="e">${esc(error)}</p>` : ""}<div class="m">${esc(q.material)}</div>` +
      `<form method="post">${hidden("confirm")}${radios}` +
      `<p><textarea name="text" rows="4" placeholder="理由・記述・質問・補足">${esc(text)}</textarea></p>` +
      `<button>確認へ</button></form>`,
    error ? 400 : 200,
  );
}

async function submit(q, env, pick, text) {
  const body = `種別: ${q.kind}\n問い: ${q.id}\n選んだもの: ${pick}\n本文: ${text}`;
  const res = await github(env, `/repos/${env.TASKS_REPO}/issues/${q.issue}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  return res.ok ? render(q, "done", pick) : html(`<p>書き込めませんでした（GitHub ${res.status}）。</p>`, 502);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/answer") return new Response("not found", { status: 404 });
    if (request.method !== "GET" && request.method !== "POST")
      return new Response("method not allowed", { status: 405 });
    const data = request.method === "POST" ? await request.formData() : url.searchParams;
    const issue = String(data.get("issue") ?? "");
    if (!/^\d+$/.test(issue)) return html("<p>問いのリンクが壊れています。</p>", 400);
    const q = await question(env, issue, data.get("from") === "body");
    if (!q) return html("<p>答える問いがありません。</p>", 404);
    const step = String(data.get("step") ?? "form");
    const pick = String(data.get("pick") ?? "");
    // 本文は道具が読む行の後ろに書くので、道具の印（コメントの囲み）を持ち込ませない。
    const text = String(data.get("text") ?? "")
      .replace(/<!--|-->/g, "")
      .trim();
    const op = q.ops.find((o) => o.key === pick);
    if (step === "form" || request.method === "GET") return render(q, "form", pick, text);
    if (!op) return render(q, "form", pick, text, "操作を1つ選んでください。");
    if (op.need && !text) return render(q, "form", pick, text, `「${op.label}」には${op.need}が要ります。`);
    return step === "send" ? submit(q, env, pick, text) : render(q, "confirm", pick, text);
  },
};
