// 遷移の表・問いと答えの形。GitHub に触れない純粋な関数だけを置く。

// 画面や Windows から書かれた本文は改行の前に \r が重なって届くことがある。
export const normalize = (text) => (text ?? "").replace(/\r+\n/g, "\n");

// 誰の番かはステータスだけで決まる（flow.config.json: owner）。閉じたものは誰の番でもない。
export const ownerOf = (config, issue) => (issue.state === "OPEN" ? (config.owner[issue.status] ?? null) : null);

// 今日（日本時間）の日付と、着手可能日が今日より先ならその日（無ければ null）。
export const today = (now = new Date()) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo" }).format(now);
export const waitsUntil = (date, now = new Date()) => (date && date > today(now) ? date : null);

// 本文の先頭の、ゲートの印の間（回答待ちの間だけ、回答フォームへのボタンを置く）。印の間だけを足し替える。
const BLOCK = /^<!-- flow-gate -->\n([\s\S]*?)<!-- \/flow-gate -->\n*/;
const BUTTON = /^\[!\[回答する\]\([^)]*\)\]\([^)]*\)$/;
export const bodyRest = (body) => normalize(body).replace(BLOCK, "");
// 印の間のうち、ゲートが書かない行（ボタンでない行）。印の間を足し替えると消えるので、ゲートが拾って印の外へ出す。
export const strayInBlock = (body) => (BLOCK.exec(normalize(body))?.[1] ?? "").split("\n").filter((l) => l.trim() && !BUTTON.test(l.trim())).join("\n");
export const withButton = (rest, url, image) => `<!-- flow-gate -->\n[![回答する](${image})](${url})\n<!-- /flow-gate -->\n\n${rest}`;

// 完了の条件のうちチェックの無いもの（本文のチェックは完了の条件にだけ使う）と、それを全部チェックした本文。
export const remaining = (body) => [...bodyRest(body).matchAll(/^\s*- \[ \] (.+)$/gm)].map((m) => m[1]);
export const checkAll = (body) => normalize(body).replace(/^(\s*- )\[ \] /gm, "$1[x] ");

// from から to への遷移を照らす。誰が・どの経路で動かしても、ここだけで決める。表（transitions）に無ければ断る。
// 表のほかのルールは1つだけで、完了へ完成（close が COMPLETED）で入るとき、body に完了の条件の残りがあれば断る。
export function judge(config, from, to, { close, body } = {}) {
  if (!(config.transitions[from] ?? []).includes(to)) return { ok: false, reason: `「${from ?? "（無し）"}」から「${to}」へは動かせません（遷移の表に無い）。` };
  const left = to === config.done && close === "COMPLETED" ? remaining(body) : [];
  if (left.length) return { ok: false, reason: `完成にするには次が残っています。\n\n${left.map((l) => `- ${l}`).join("\n")}\n\n` };
  return { ok: true };
}

// 問い（docs/conventions/flow.md「問い」）: 「## 問い」の行・問いの文1行・（あれば）「### 案」と1行1案・（あれば）<details> の
// 判断材料だけ。ほかの行があれば形に合わないので null。
export function parseQuestion(text) {
  const all = normalize(text);
  const cut = all.indexOf("<details>");
  const [first, ...lines] = (cut < 0 ? all : all.slice(0, cut)).split("\n");
  if (first.trim() !== "## 問い") return null;
  const [question, header, ...plans] = lines.map((l) => l.trim()).filter(Boolean);
  if (!question || /^(#|- )/.test(question)) return null;
  if (header !== undefined && (header !== "### 案" || !plans.length || plans.some((l) => !l.startsWith("- ")))) return null;
  const material = cut < 0 ? "" : (/^<details>\s*<summary>[^<]*<\/summary>([\s\S]*?)<\/details>/.exec(all.slice(cut))?.[1].trim() ?? "");
  return { text: question, plans: plans.map((l) => l.slice(2).trim()), material };
}

// 回答フォームの次のステータス: 表で今のステータスから行ける先。完了は完成と見送りに分ける。最初のものが既定。
export const nextChoices = (config, from) =>
  config.transitions[from].flatMap((to) =>
    to === config.done ? [{ to, close: "COMPLETED", text: "完成" }, { to, close: "NOT_PLANNED", text: "見送り" }] : [{ to, text: to }]);

// 答えのコメント（問いのコメントの後ろに続く）。
export const answerBody = ({ question, plan, choice, checked, added, removed, note }) =>
  [
    "## 回答", `**${question.text}**`, "",
    ...(plan ? [`回答: ${plan}`] : []),
    `次のステータス: ${choice.text}`,
    ...checked.map((c) => `- [x] ${c}`),
    ...(added.length || removed.length ? [`ラベル: ${[...added.map((n) => `+${n}`), ...removed.map((n) => `−${n}`)].join(" ")}`] : []),
    ...(note ? [`補足: ${note}`] : []),
  ].join("\n");

// 回答フォームへのボタンの画像（GitHub の画面にはボタンを足せないので、本文の先頭にリンク付きの画像として置く）。
export const BUTTON_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" width="152" height="44" viewBox="0 0 152 44"><rect width="152" height="44" rx="8" fill="#1f6feb"/>` +
  `<text x="76" y="28" text-anchor="middle" font-size="17" font-weight="700" fill="#fff" ` +
  `font-family="system-ui,-apple-system,'Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif">回答する</text></svg>`;
