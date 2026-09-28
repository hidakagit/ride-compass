// 遷移の表・問いと答えの形。GitHub に触れない純粋な関数だけを置く。

export const personById = (config, id) => Object.keys(config.people).find((k) => config.people[k].id === id) ?? null;
export const personByShown = (config, shown) =>
  Object.keys(config.people).find((k) => config.people[k].shown === shown) ?? null;

export function entryFor(config, authorId) {
  const author = personById(config, authorId);
  return config.entry.find((e) => e.author === author) ?? config.entry.find((e) => e.author === null);
}

export const ruleFor = (config, from, to) =>
  config.transitions.find((t) => t.from.includes(from) && t.to.includes(to)) ?? null;

// 表で照らす。blockers は前提の issue（{ number, state, stateReason }）。
export function check(config, from, to, blockers = []) {
  const rule = ruleFor(config, from, to);
  if (!rule) return { ok: false, reason: `「${from ?? "（無し）"}」から「${to ?? "（無し）"}」へは動かせません（遷移の表に無い）。` };
  if (rule.when === "blockersCompleted") {
    const open = blockers.filter((b) => !(b.state === "CLOSED" && b.stateReason === "COMPLETED"));
    if (open.length)
      return { ok: false, reason: `前提 ${open.map((b) => `#${b.number}`).join("・")} が完了（completed）で閉じていないため、「${to}」にできません。` };
  }
  return { ok: true, rule };
}

// 問いのコメントを読む。形（docs/conventions/flow.md「問い」）に合わなければ null。
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
    const option = { text: label.trim(), to: null, next: null, labels: [] };
    for (const part of rest ? rest.split(" / ").map((p) => p.trim()) : []) {
      if (part.startsWith("+")) option.labels.push(part.slice(1));
      else if (config.statuses.includes(part)) option.to = part;
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
  const options = config.adoption.options.map(
    (o) => `- ${o.text} → ${[o.to, o.next && shown(o.next), ...(o.labels ?? []).map((l) => `+${l}`)].filter(Boolean).join(" / ")}`,
  );
  return `## 問い\n${config.adoption.question}\n\n### 選択肢\n${options.join("\n")}\n`;
}

// フォームに出す選択肢。問いの選択肢とフォームが必ず足す選択肢のうち、今のステータスから表で行けるものだけ。
export function formChoices(config, question, current) {
  return [...question.options, ...config.formOptions]
    .map((o) => {
      const to = o.to ?? current;
      const rule = to === current ? null : ruleFor(config, current, to);
      const next = to === config.done ? null : (o.next ?? rule?.assign ?? "hidakagit-bot");
      return { text: o.text, to, next, labels: o.labels ?? [], note: Boolean(o.note), ok: to === current || rule };
    })
    .filter((c) => c.ok)
    .map(({ ok, ...c }) => c);
}

export function answerBody(config, { questionUrl, choice, next, note }) {
  return [
    "## 回答",
    `問い: ${questionUrl}`,
    `選んだもの: ${choice.text}`,
    `次のステータス: ${choice.to}`,
    ...(next ? [`次に動くのは: ${config.people[next].shown}`] : []),
    ...(note ? [`補足: ${note}`] : []),
  ].join("\n");
}

// 本文の先頭に置く、答えを待っていることと回答フォームへのリンクの1行。印の間だけを足し替え、本文の中身には触れない。
const BANNER = /^<!-- flow-gate -->\n[\s\S]*?\n<!-- \/flow-gate -->\n*/;
export const withoutBanner = (body) => (body ?? "").replace(/\r\n/g, "\n").replace(BANNER, "");
export const withBanner = (body, status, text, url) =>
  `<!-- flow-gate -->\n**${status}**: ${text} → [回答フォーム](${url})\n<!-- /flow-gate -->\n\n${withoutBanner(body)}`;

export const answers = (body, questionUrl) =>
  body.startsWith("## 回答\n") && body.split("\n")[1] === `問い: ${questionUrl}`;
