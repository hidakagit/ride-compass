// 遷移の表・問いと答えの形。GitHub に触れない純粋な関数だけを置く。

const personById = (config, id) => Object.keys(config.people).find((k) => config.people[k].id === id) ?? null;

// 誰の番かはステータスだけで決まる（flow.config.json: owner）。閉じた・ステータスの無いものは誰の番でもない。
export const ownerOf = (config, issue) => (issue.state === "OPEN" ? (config.owner[issue.status] ?? null) : null);
export const userTurn = (config, issue) => ownerOf(config, issue) === config.user;

// 前提のうち、まだ開いているもの。見送りで閉じた前提は待たない（作る担当が読んで、進める前に問う）。
export const openBlockers = (blockers) => blockers.filter((b) => b.state !== "CLOSED");

// 入口の行: 親のある issue（段階）は「parent」の行、ほかは書いた人の行、無ければ author が null の行。
export function entryFor(config, issue) {
  if (issue.parent) return config.entry.find((e) => e.parent);
  const author = personById(config, issue.author?.databaseId);
  return config.entry.find((e) => !e.parent && e.author === author) ?? config.entry.find((e) => !e.parent && e.author === null);
}

// from から to への遷移を表で照らす。on（出来事）・by（起こす者）を渡すと、その行に限る。blockers は前提の issue。
export function check(config, from, to, { on, by, blockers = [] } = {}) {
  const rule = config.transitions.find((t) => t.from.includes(from) && t.to.includes(to) && (!on || t.on === on) && (!by || t.by === by));
  if (!rule) return { ok: false, reason: `「${from ?? "（無し）"}」から「${to ?? "（無し）"}」へは動かせません（遷移の表に無い）。` };
  if (rule.when === "blockersClosed") {
    const open = openBlockers(blockers);
    if (open.length) return { ok: false, reason: `前提 ${open.map((b) => `#${b.number}`).join("・")} が閉じていないため、「${to}」にできません。` };
  }
  return { ok: true, rule };
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

// 問いを読む（docs/conventions/flow.md「問い」）: 1行目が「## 問い」、次の行が問いの文、「### 案」の下の箇条書きが案、
// <details> の中が判断材料。問いの文が無ければ null。
// 前の形の問い（「### 選択肢」の各行に「→ 行き先 / 次に動く者」）も読む: 行き先を外して案にし、回答フォームが一律に出す
// 「進める」以外の選択肢（止める・完成・見送り）と同じ行き先のものは落とす。
export function parseQuestion(config, body) {
  const lines = normalizeBody(body).split("\n");
  if (lines[0].trim() !== "## 問い") return null;
  const text = lines.slice(1).find((l) => l.trim())?.trim();
  if (!text || text.startsWith("#")) return null;
  const go = config.answers.find((a) => a.plans).to;
  const covered = config.answers.map((a) => a.to).filter((s) => s !== go);
  const plans = [];
  const at = lines.findIndex((l) => ["### 案", "### 選択肢"].includes(l.trim()));
  for (const line of at < 0 ? [] : lines.slice(at + 1)) {
    if (!line.startsWith("- ")) {
      if (line.trim() || plans.length) break;
      continue;
    }
    const [plan, to] = line.slice(2).split("→");
    if (!covered.includes(to?.split("/")[0].trim())) plans.push(plan.trim());
  }
  const material = /<details>\s*<summary>[^<]*<\/summary>([\s\S]*?)<\/details>/.exec(body)?.[1].trim() ?? "";
  return { text, plans: plans.filter(Boolean), material };
}

export const questionBody = (text) => `## 問い\n${text}`;

// 回答フォームの選択肢。問いによらず flow.config.json: answers から、今のステータスから「回答」で行ける先だけを一律に出す。
// 問いに案があれば、「進める」を案の数だけに分ける（行き先は同じで、選んだ案が答えに残る）。
export function answerChoices(config, question, current) {
  return config.answers
    .filter((a) => a.to !== current && check(config, current, a.to, { on: "回答" }).ok)
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
