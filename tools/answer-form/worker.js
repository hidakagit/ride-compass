// 段の問いへの回答ページ。規約は docs/conventions/flow.md「ユーザーが答える形」。
// 書く先は env.TASKS_REPO の issue だけ。秘密の値 env.GITHUB_TOKEN はそのリポジトリの Issues: write だけを持つ。
// scripts/flow.py: ANSWER_RE がコメントの1行目「回答: <記号>（<選択肢>）」を読む。
const SYMBOLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const ANSWER = /^[A-Z]（[^\r\n]+）$/;

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const page = (body, status = 200) =>
  new Response(
    `<!doctype html><html lang="ja"><head><meta charset="utf-8">` +
      `<meta name="viewport" content="width=device-width,initial-scale=1"><title>回答</title><style>` +
      `body{font:17px/1.6 system-ui,sans-serif;max-width:32rem;margin:1rem auto;padding:0 16px}` +
      `label{display:block;padding:.8rem;border:1px solid #bbb;border-radius:.5rem;margin:.5rem 0}` +
      `textarea{width:100%;box-sizing:border-box;font:inherit}button{font:inherit;padding:.7rem 1.6rem}` +
      `</style></head><body>${body}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );

function form(url) {
  const issue = url.searchParams.get("issue") ?? "";
  const options = url.searchParams.getAll("o").filter(Boolean).slice(0, SYMBOLS.length);
  if (!/^\d+$/.test(issue) || options.length === 0) return page("<p>問いのリンクが壊れています。</p>", 400);
  const radios = options
    .map((o, i) => {
      const value = esc(`${SYMBOLS[i]}（${o}）`);
      return `<label><input type="radio" name="answer" value="${value}" required> ${SYMBOLS[i]}. ${esc(o)}</label>`;
    })
    .join("");
  return page(
    `<h1>#${issue} への回答</h1><form method="post"><input type="hidden" name="issue" value="${issue}">` +
      `${radios}<p><textarea name="note" rows="3" placeholder="補足（任意）"></textarea></p>` +
      `<button>送信</button></form>`,
  );
}

async function submit(request, env) {
  const data = await request.formData();
  const issue = String(data.get("issue") ?? "");
  const answer = String(data.get("answer") ?? "");
  const note = String(data.get("note") ?? "").trim();
  if (!/^\d+$/.test(issue) || !ANSWER.test(answer)) return page("<p>選択肢を1つ選んでから送信してください。</p>", 400);
  const res = await fetch(`https://api.github.com/repos/${env.TASKS_REPO}/issues/${issue}/comments`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "ride-compass-answer-form",
    },
    body: JSON.stringify({ body: `回答: ${answer}` + (note ? `\n\n補足: ${note}` : "") }),
  });
  if (!res.ok) return page(`<p>書き込めませんでした（GitHub ${res.status}）。</p>`, 502);
  return page(`<p>受け付けました（#${issue}: ${esc(answer)}）。</p>`);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/answer") return new Response("not found", { status: 404 });
    if (request.method === "GET") return form(url);
    if (request.method === "POST") return submit(request, env);
    return new Response("method not allowed", { status: 405 });
  },
};
