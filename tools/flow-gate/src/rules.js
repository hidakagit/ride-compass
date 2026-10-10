// 遷移の表・問いと答えの形。GitHub に触れない純粋な関数だけを置く。

// 画面や Windows から書かれた本文は改行の前に \r が重なって届くことがある。
export const normalize = (text) => (text ?? "").replace(/\r+\n/g, "\n");
export const SCAN = 30; // 今の問いを探すために読むコメントの件数（回答フォーム・ask.js）

// 誰の番かはステータスだけで決まる（flow.config.json: owner）。閉じたものは誰の番でもない。
export const ownerOf = (config, issue) => (issue.state === "OPEN" ? (config.owner[issue.status] ?? null) : null);

// 今日（日本時間）の日付と、着手可能日が今日より先ならその日（無ければ null）。
const today = (now = new Date()) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo" }).format(now);
const waitsUntil = (date, now = new Date()) => (date && date > today(now) ? date : null);

// 作る担当へ振り出さずに待つ理由（無ければ null）: 開いた前提・ラベル coordinator.devLabel・今日より先の着手可能日。見回り
// （src/dispatch.js: ready）と後始末（src/after.js: settle）が同じ見分けを使う。
export const waitsFor = (config, { blocked, labels, startOn }, now = new Date()) =>
  blocked ? "開いた前提（blocked by）" : labels.includes(config.coordinator.devLabel) ? `ラベル「${config.coordinator.devLabel}」`
    : waitsUntil(startOn, now) ? `着手可能日 ${startOn}` : null;

// 本文の先頭の、ゲートの印の間（回答待ちの間だけ、回答フォームへのボタンを置く）。印の間だけを足し替える。
const BLOCK = /^<!-- flow-gate -->\n[\s\S]*?<!-- \/flow-gate -->\n*/;
export const bodyRest = (body) => normalize(body).replace(BLOCK, "");
export const withButton = (rest, url, image) => `<!-- flow-gate -->\n[![回答する](${image})](${url})\n<!-- /flow-gate -->\n\n${rest}`;

// 完了の条件のうちチェックの無いもの（本文のチェックは完了の条件にだけ使う）と、それを全部チェックした本文。
export const remaining = (body) => [...bodyRest(body).matchAll(/^\s*- \[ \] (.+)$/gm)].map((m) => m[1]);
export const checkAll = (body) => normalize(body).replace(/^(\s*- )\[ \] /gm, "$1[x] ");

// from から to への遷移を照らす。誰が・どの経路で動かしても、ここだけで決める。表（transitions）に無ければ断る。
// 表のほかのルールは2つ: 完了へ完成（close が COMPLETED）で入るとき、body に完了の条件の残りがあれば断る。回答待ちへ入るとき、
// comments（古い順の本文。同じ要求で書くコメントも含める）の最新の問いか答えが、形に合う問いでなければ断る。
export function judge(config, from, to, { close, body, comments = [] } = {}) {
  if (!(config.transitions[from] ?? []).includes(to)) return { ok: false, reason: `「${from ?? "（無し）"}」から「${to}」へは動かせません（遷移の表に無い）。` };
  const left = to === config.done && close === "COMPLETED" ? remaining(body) : [];
  if (left.length) return { ok: false, reason: `完成にするには次が残っています。\n\n${left.map((l) => `- ${l}`).join("\n")}\n\n` };
  const asked = to === config.waiting ? checkQuestion(config.questionTemplate, comments.findLast((b) => /^## (問い|回答)\n/.test(normalize(b)))) : [];
  return asked.length ? { ok: false, reason: `回答待ちには、答えていない問いが形（tools/flow-gate/question_template.md）のとおりに要ります: ${asked.join("・")}。` } : { ok: true };
}

// 節の形（Pull Request の本文・問いの判断材料）: 節は、行の頭の「<名前>:」（「**<名前>**:」も）から次の節の頭の前まで。名前は
// テンプレートの節の頭の行から取り、ほかの「名前: 」の行は節の中身とする。
const HEAD = /^(?:\*\*)?([^\s:*<>`]+)(?:\*\*)?:(.*)$/;
const split = (text, names) => {
  const out = [];
  for (const line of normalize(text).split("\n")) {
    const m = HEAD.exec(line);
    if (m && (!names || names.includes(m[1]))) out.push({ name: m[1], lines: [m[2]] });
    else if (out.length) out.at(-1).lines.push(line);
    else if (line.trim()) out.push({ name: null, lines: [line] });
  }
  return out.map(({ name, lines }) => ({ name, text: lines.join("\n").trim() }));
};

// 本文の形の誤りを1件1行で返す（無ければ空）: テンプレートの節を、この順に1つずつ、埋めて持つ。
export function checkBody(template, body) {
  const want = split(template).filter((s) => s.name);
  const names = want.map((s) => s.name);
  const got = split(body, names);
  const problems = [];
  if (got[0]?.name === null) problems.push(`最初の節「${names[0]}:」より前に行がある: ${got[0].text.split("\n")[0]}`);
  const order = got.filter((s) => s.name).map((s) => s.name);
  if (order.join("・") !== names.join("・")) problems.push(`節は「${names.join("・")}」をこの順に1つずつ置く（本文の節: 「${order.join("・")}」）`);
  for (const s of got.filter((s) => s.name)) {
    if (!s.text) problems.push(`節「${s.name}:」が空`);
    else if (s.text === want.find((w) => w.name === s.name).text) problems.push(`節「${s.name}:」がテンプレートのまま`);
  }
  return problems;
}

// 問いの誤り（無ければ空）: 行の並びは parseQuestion、判断材料は形（tools/flow-gate/question_template.md。設定の questionTemplate）の節。
export const checkQuestion = (template, text) =>
  parseQuestion(text) ? checkBody(parseQuestion(template).material, parseQuestion(text).material) : ["「## 問い」・問いの文（1行）・「### 案」と1行1案・<details> の判断材料のほかに行がある（か、問いでない）"];

// 問い（.claude/skills/ask/SKILL.md「問い」）: 「## 問い」の行・問いの文1行・（あれば）「### 案」と1行1案・（あれば）<details> の
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

// ステータスを動かすときに issue へ残すコメント。見回りの作業時間（src/dispatch.js: workload）は同じ形を worksAfter で読むので、
// 形を変えるときは worksAfter も一緒に変える。
export const notes = {
  start: (kind, url) => `### ${kind}担当の着手\n\n実行: ${url}`,
  reason: (to, why) => `${to}にする理由: ${why}`,
  back: (why, from) => `${why}「${from}」へ戻しました。`,
  // ゲートが Pull Request の閉じで書く。どれもタスクを未着手か完了へ動かす。
  pullRequest: (pr, rest) => `Pull Request [#${pr.number} ${pr.title.replace(/[[\]]/g, "\\$&")}](${pr.html_url}) ${rest}`,
};

// コメント（notes の形か問い）の直後に、タスクが作業の状態（進行中・検証中）にいるか。記録の形でなければ null。
// 着手は作る担当なら進行中へ動かし、確かめる担当なら検証中のまま書く。
export function worksAfter(config, body) {
  const text = normalize(body);
  if (parseQuestion(text) || /^Pull Request \[#\d+ /.test(text)) return false;
  if (/^### \S+?担当の着手\n/.test(text)) return true;
  const to = /^(\S+?)にする理由: /.exec(text)?.[1] ?? /「([^」]+)」へ戻しました。$/.exec(text)?.[1];
  return config.statuses.includes(to) ? [config.working, config.review].includes(to) : null;
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
