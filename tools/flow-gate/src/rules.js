// 遷移の表・問いと答えの形。GitHub に触れない純粋な関数だけを置く。

const personById = (config, id) => Object.keys(config.people).find((k) => config.people[k].id === id) ?? null;

// 誰の番かはステータスだけで決まる（flow.config.json: owner）。閉じた・ステータスの無いものは誰の番でもない。
export const ownerOf = (config, issue) => (issue.state === "OPEN" ? (config.owner[issue.status] ?? null) : null);
export const userTurn = (config, issue) => ownerOf(config, issue) === config.user;

// 前提のうち、まだ開いているもの。見送りで閉じた前提は待たない（作る担当が読んで、進める前に問う）。
export const openBlockers = (blockers) => blockers.filter((b) => b.state !== "CLOSED");

// 子（段階）のうち、まだ開いているもの。開いた子のある親の仕事は子で進み、子が全部閉じるとゲートが親を閉じる。
export const openChildren = (children) => children.filter((c) => c.state === "OPEN");

// 入口の行: 親のある issue（段階）は「parent」の行、ほかは書いた人の行、無ければ author が null の行。
export function entryFor(config, issue) {
  if (issue.parent) return config.entry.find((e) => e.parent);
  const author = personById(config, issue.author?.databaseId);
  return config.entry.find((e) => !e.parent && e.author === author) ?? config.entry.find((e) => !e.parent && e.author === null);
}

// Claude が欄を書き換えてよいか。既定値（flow.config.json: project.defaults）を持つ欄で、今の値が既定と違えば
// 誰かが決めた値（ユーザーが付けた・起票で見積もった・親から継いだ）なので、別の値へは書き換えない。断るなら理由、通すなら null。
export function fieldRefusal(config, name, current, value) {
  const fallback = config.project.defaults[name];
  if (!fallback || !current || current === fallback || current === value) return null;
  return `欄「${name}」の今の値「${current}」は既定（${fallback}）と違う、決めてある値なので書き換えません。変えるならユーザーに問います。`;
}

// from から to への遷移を照らす。誰が・どの経路で動かしても、ここだけで決める。表（flow.config.json: transitions。FROM ごとに
// 行ける TO の並び）に無ければ断る。表のほかのルールは1つだけで、完了へ完成（close が COMPLETED）で入るときに完了の条件の
// 残り（remaining）があれば断る。見送り（NOT_PLANNED）は条件を問わない。issue は残りを読むためのタスク。
export function judge(config, from, to, { close, issue } = {}) {
  const tos = config.transitions[from] ?? [];
  if (!tos.includes(to))
    return { ok: false, reason: tos.length ? `「${from}」から「${to}」へは動かせません（遷移の表に無い）。` : `「${from ?? "（無し）"}」からはどこへも動かせません（遷移の表に無い）。` };
  const left = to === config.done && close === "COMPLETED" && issue ? remaining(config, issue) : [];
  if (left.length) return { ok: false, reason: `完成にするには次が残っています。\n\n${left.map((l) => `- ${l}`).join("\n")}\n\n` };
  return { ok: true };
}

// 本文のチェックの無い項目（`- [ ]`。本文のチェックは完了の条件にだけ使う）。
const unchecked = (body) =>
  splitBody(body)
    .rest.split("\n")
    .map((l) => /^\s*- \[ \] (.+)$/.exec(l)?.[1])
    .filter(Boolean);

// 完成と言える前に残っているもの: チェックの無い完了の条件と、ユーザーの確認（ラベル confirmLabel）。
export const remaining = (config, issue) => [
  ...unchecked(issue.body),
  ...(issue.labels.nodes.some((l) => l.name === config.confirmLabel) ? [`ユーザーの確認（ラベル「${config.confirmLabel}」）`] : []),
];

// 問いを読む（docs/conventions/flow.md「問い」）。最初の <details> から後ろは判断材料で、中身を解釈しない。それより前に
// 置けるのは、1行目の「## 問い」・問いの文（1行）・「### 案」とその下の「- 」の行（1行に1案、書いたとおり）・空行だけで、
// ほかの行が1行でもあれば形に合わないので null。
export function parseQuestion(body) {
  const all = normalizeBody(body);
  const cut = all.indexOf("<details>");
  const [first, ...lines] = (cut < 0 ? all : all.slice(0, cut)).split("\n");
  if (first.trim() !== "## 問い") return null;
  const [text, header, ...items] = lines.map((l) => l.trim()).filter(Boolean);
  if (!text || text.startsWith("#") || text.startsWith("- ")) return null;
  if (header !== undefined && (header !== "### 案" || !items.length || items.some((l) => !l.startsWith("- ")))) return null;
  const material = cut < 0 ? "" : (/^<details>\s*<summary>[^<]*<\/summary>([\s\S]*?)<\/details>/.exec(all.slice(cut))?.[1].trim() ?? "");
  return { text, plans: items.map((l) => l.slice(2).trim()), material };
}

export const questionBody = (text) => `## 問い\n${text}`;

// 回答フォームの選択肢。問いによらず flow.config.json: answers から、今のステータスから「回答」で行ける先だけを一律に出す。
// 問いに案があれば、「進める」を案の数だけに分ける（行き先は同じで、選んだ案が答えに残る）。
export function answerChoices(config, question, current) {
  return config.answers
    .filter((a) => a.to !== current && judge(config, current, a.to).ok)
    .flatMap((a) => (a.plans && question.plans.length ? question.plans.map((p) => ({ ...a, text: `「${p}」で${a.text}` })) : [a]));
}

// 答えのコメント。問いは答えると本文から消えるので、問い・選択肢・判断材料もここに残す（このコメント1つで読める）。
export function answerBody({ question, choices, choice, note, added = [], removed = [] }) {
  return [
    "## 回答",
    `**${question.text}**`,
    "",
    ...choices.map((c) => (c === choice ? `● **${c.text}**` : `○ ${c.text}`)),
    "",
    `次のステータス: ${choice.to}`,
    ...(added.length || removed.length ? [`ラベル: ${[...added.map((n) => `+${n}`), ...removed.map((n) => `−${n}`)].join(" ")}`] : []),
    ...(note ? [`補足: ${note}`] : []),
    ...(question.material ? ["", `<details><summary>判断材料</summary>\n\n${question.material}\n</details>`] : []),
  ].join("\n");
}

// 本文の先頭の、ゲートの印の間。答えを待つ問い（画面に出ない HTML のコメント）と、ボタンとステータスの行を置く。
// 印の間だけを足し替え、本文の中身には触れない。
const BLOCK = /^<!-- flow-gate -->\n([\s\S]*?)\n?<!-- \/flow-gate -->\n*/;
const QUESTION = /<!-- 問い\n([\s\S]*?)\n-->/;

export const normalizeBody = (body) => (body ?? "").replace(/\r\n/g, "\n");

export function splitBody(body) {
  const text = normalizeBody(body);
  const m = BLOCK.exec(text);
  return { question: (m && QUESTION.exec(m[1])?.[1]) ?? null, rest: m ? text.slice(m[0].length) : text };
}

// button は { status, text, url, image }。問いもボタンも無ければ印ごと置かない。
export function joinBody(rest, question, button) {
  const parts = [
    ...(question ? [`<!-- 問い\n${question}\n-->`] : []),
    ...(button ? [`[![回答する](${button.image})](${button.url})\n\n**${button.status}**: ${button.text}`] : []),
  ];
  return parts.length ? `<!-- flow-gate -->\n${parts.join("\n")}\n<!-- /flow-gate -->\n\n${rest}` : rest;
}

// 本文の先頭に置く回答フォームへのボタンの画像。GitHub の画面にはボタンを足せないので、本文の先頭にリンク付きの画像として置く。
export const BUTTON_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" width="152" height="44" viewBox="0 0 152 44"><rect width="152" height="44" rx="8" fill="#1f6feb"/>` +
  `<text x="76" y="28" text-anchor="middle" font-size="17" font-weight="700" fill="#fff" ` +
  `font-family="system-ui,-apple-system,'Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif">回答する</text></svg>`;
