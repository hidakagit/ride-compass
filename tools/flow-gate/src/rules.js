// 遷移の表・問いと答えの形。GitHub に触れない純粋な関数だけを置く。

const personById = (config, id) => Object.keys(config.people).find((k) => config.people[k].id === id) ?? null;
const personByShown = (config, shown) => Object.keys(config.people).find((k) => config.people[k].shown === shown) ?? null;

// Claude（問いを書く側）。Claude の番は、これに割り当たっているもの。
export const claude = (config) => config.ask.askers[0];

// 答える人（ask.answerer）の番か: 開いていて、答える人に割り当たっている。
export const answererTurn = (config, issue) =>
  issue.state === "OPEN" && issue.assignees.nodes.some((a) => a.id === config.people[config.ask.answerer].node);

// 前提のうち、完了（completed）で閉じていないもの。
export const openBlockers = (blockers) => blockers.filter((b) => !(b.state === "CLOSED" && b.stateReason === "COMPLETED"));

// 入口の行: 親のある issue（段階）は「parent」の行、ほかは書いた人の行、無ければ author が null の行。
export function entryFor(config, issue) {
  if (issue.parent) return config.entry.find((e) => e.parent);
  const author = personById(config, issue.author?.databaseId);
  return config.entry.find((e) => !e.parent && e.author === author) ?? config.entry.find((e) => !e.parent && e.author === null);
}

const ruleFor = (config, from, to) => config.transitions.find((t) => t.from.includes(from) && t.to.includes(to)) ?? null;

// 表で照らす。blockers は前提の issue（{ number, state, stateReason }）。
export function check(config, from, to, blockers = []) {
  const rule = ruleFor(config, from, to);
  if (!rule) return { ok: false, reason: `「${from ?? "（無し）"}」から「${to ?? "（無し）"}」へは動かせません（遷移の表に無い）。` };
  if (rule.when === "blockersCompleted") {
    const open = openBlockers(blockers);
    if (open.length)
      return { ok: false, reason: `前提 ${open.map((b) => `#${b.number}`).join("・")} が完了（completed）で閉じていないため、「${to}」にできません。` };
  }
  return { ok: true, rule };
}

// 問いを読む。形（docs/conventions/flow.md「問い」）に合わなければ null。
export function parseQuestion(config, body) {
  const lines = body.replace(/\r/g, "").split("\n");
  if (lines[0].trim() !== "## 問い") return null;
  const text = lines.slice(1).find((l) => l.trim())?.trim();
  const at = lines.findIndex((l) => l.trim() === "### 選択肢");
  if (!text || text.startsWith("#") || at < 0) return null;
  const options = [];
  for (const line of lines.slice(at + 1)) {
    if (!line.trim()) {
      if (options.length) break;
      continue;
    }
    if (!line.startsWith("- ")) break;
    const [label, rest] = line.slice(2).split(" → ");
    const option = { text: label.trim(), to: null, next: null };
    for (const part of rest ? rest.split(" / ").map((p) => p.trim()) : []) {
      if (config.statuses.includes(part)) option.to = part;
      else if (personByShown(config, part)) option.next = personByShown(config, part);
      else return null;
    }
    if (!option.text) return null;
    options.push(option);
  }
  if (options.length < 2) return null;
  const material = /<details>\s*<summary>[^<]*<\/summary>([\s\S]*?)<\/details>/.exec(body)?.[1].trim() ?? "";
  return { text, options, material };
}

export function adoptionQuestion(config) {
  const shown = (key) => config.people[key].shown;
  const options = config.adoption.options.map((o) => `- ${o.text} → ${[o.to, o.next && shown(o.next)].filter(Boolean).join(" / ")}`);
  return `## 問い\n${config.adoption.question}\n\n### 選択肢\n${options.join("\n")}\n`;
}

// フォームに出す選択肢。問いの選択肢とフォームが必ず足す選択肢のうち、今のステータスから表で行けるもの（前提も照らす）だけ。
// ステータスは選択肢に書いた行き先だけで決まる。行き先を書いていない選択肢（「その他」を含む）は状態を決めず、今のままで
// 問いを書く側（Claude）の番になる。Claude は補足を読んで問い直すだけで、ステータスを動かさない。
export function formChoices(config, question, current, blockers = []) {
  return [...question.options, ...config.formOptions]
    .map((o) => {
      const to = o.to ?? current;
      const fixed = to === current;
      const verdict = fixed ? { ok: true } : check(config, current, to, blockers);
      const next = to === config.done ? null : fixed ? claude(config) : (o.next ?? verdict.rule?.assign ?? claude(config));
      return { text: o.text, to, next, fixed, note: Boolean(o.note), close: o.close ?? null, ok: verdict.ok };
    })
    .filter((c) => c.ok)
    .map(({ ok, ...c }) => c);
}

// 答える人の番なのに答える問いが無いときの問い（what）。選択肢は、表で今のステータスから行ける先と、閉じ方（見送り・完成）。
// 回答待ちへは問いと一緒にしか入れず、保留へは「止める」で入り、進行中は司令塔が担当を渡すときだけ入れるので、ここには出さない。
// why は、なぜここへ来たか（判断材料の文）。
export function whatQuestion(config, status, why) {
  const skip = [status, config.ask.status, config.hold, config.done, config.verify.from];
  const targets = [...new Set(config.transitions.filter((t) => t.from.includes(status)).flatMap((t) => t.to))].filter((to) => !skip.includes(to));
  const options = [...targets.map((to) => ({ text: config.what.move.replace("{to}", to), to, next: null })), ...config.what.options];
  return { text: config.what.question, options, material: `いまのステータスは「${status ?? "無し"}」です。${why}` };
}

// 答えのコメント。問いは答えると本文から消えるので、問い・選択肢・判断材料もここに残す（このコメント1つで読める）。
export function answerBody(config, { question, choices, choice, next, note, added = [], removed = [] }) {
  return [
    "## 回答",
    `**${question.text}**`,
    "",
    ...choices.map((c) => (c === choice ? `● **${c.text}**` : `○ ${c.text}`)),
    "",
    `次のステータス: ${choice.to}`,
    ...(next ? [`次に動くのは: ${config.people[next].shown}`] : []),
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
    ...(button ? [`[![${BUTTON_LABEL}](${button.image})](${button.url})\n\n**${button.status}**: ${button.text}`] : []),
  ];
  return parts.length ? `<!-- flow-gate -->\n${parts.join("\n")}\n<!-- /flow-gate -->\n\n${rest}` : rest;
}

// 答える人（ask.answerer）の番の間は、どのステータスでも本文の先頭にボタンを1つとステータスの行を置く。ボタンは回答フォームの
// 入口を指し、行き先は押した時点で回答フォームが決める（本文は出来事が来たときにしか書き直されず、書いた時点の行き先は古くなるため）。
// 答えを待つ問いは、答えるまで同じ場所に画面に出ない形で残す。links は { form: 回答フォームの origin, image: ボタンの画像の URL }。
export function turnBody(config, links, issue) {
  const { question, rest } = splitBody(issue.body);
  if (!answererTurn(config, issue)) return joinBody(rest, question, null);
  const q = issue.status === config.ask.status && question ? parseQuestion(config, question) : null;
  const url = `${links.form}/answer?issue=${issue.number}`;
  return joinBody(rest, question, { status: issue.status ?? "無し", text: q?.text ?? config.what.question, url, image: links.image });
}

// 本文の先頭に置くボタンの画像。GitHub の画面にはボタンを足せないので、本文の先頭にリンク付きの画像として置く。
const BUTTON_LABEL = "対応する";
export const BUTTON_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" width="152" height="44" viewBox="0 0 152 44"><rect width="152" height="44" rx="8" fill="#1f6feb"/>` +
  `<text x="76" y="28" text-anchor="middle" font-size="17" font-weight="700" fill="#fff" ` +
  `font-family="system-ui,-apple-system,'Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif">${BUTTON_LABEL}</text></svg>`;
