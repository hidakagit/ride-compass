// 事実からステータスを決める表・問いと答えと本文の形。GitHub に触れない純粋な関数だけを置く。

// 画面や Windows から書かれた本文は改行の前に \r が重なって届くことがある。
export const normalize = (text) => (text ?? "").replace(/\r+\n/g, "\n");
export const SCAN = 30; // 今の問いを探すために読むコメントの件数（ゲート・回答フォーム・ask.js）

// 着手可能日時（project.startField）の値を YYYY-MM-DD HH:MM（日本時間）にそろえる。時刻を省いた YYYY-MM-DD は 00:00。
// 形の合わない値・無い日時は null。
export function startAt(value) {
  const [, day, time = "00:00"] = /^(\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?$/.exec(value) ?? [];
  const at = day && new Date(`${day}T${time}Z`); // 無い日時（2月30日・24:00）は NaN か別の日時になる
  return at && !Number.isNaN(at.getTime()) && at.toISOString().startsWith(`${day}T${time}`) ? `${day} ${time}` : null;
}

// 着手可能日時のために待つか: 今（日本時間の分。夏時間を持たないので UTC に9時間足す）より後の日時か、形の合わない値（ユーザーが
// ボードで書いたもの）。見回りの振り出し（src/dispatch.js: ready）と表（decide）が同じ見分けを使う。
export const startWaits = (start, now = new Date()) =>
  Boolean(start) && (startAt(start) ?? "~") > new Date(now.getTime() + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " ");

// 本文の先頭の、ゲートの印の間（答えの無い問いがある間だけ、回答フォームへのボタンを置く）。印の間だけを足し替える。
const BLOCK = /^<!-- flow-gate -->\n[\s\S]*?<!-- \/flow-gate -->\n*/;
export const bodyRest = (body) => normalize(body).replace(BLOCK, "");
export const withButton = (rest, url, image) => `<!-- flow-gate -->\n[![回答する](${image})](${url})\n<!-- /flow-gate -->\n\n${rest}`;

// 問いの種類。採否・確かめ・イレギュラーはゲートが出し、判断は担当が ask.js で出す。種類の無い「## 問い」（前の形）は判断として読む。
export const KINDS = ["採否", "判断", "確かめ", "イレギュラー"];
const QUESTION = /^## 問い(?:（(\S+?)）)?$/;
// 答えの決定。続けるなら表で決め直す。回答フォームが種類ごとに出す選び方（文と決定）。判断と確かめは選ばせない（続けるか、確かめの項目で決まる）。
export const CHOICES = { 採否: [["やる", "続ける"], ["見送り", "見送り"], ["保留", "保留"]], イレギュラー: [["もう一度やる", "続ける"], ["保留", "保留"], ["見送り", "見送り"]] };

// 問いか答えのコメントか。最新のものが問いなら、答えの無い問いがある。
const kindOf = (body) => normalize(body).startsWith("## 回答\n") ? "答え" : QUESTION.test(normalize(body).split("\n")[0]) ? "問い" : null;
export const unanswered = (bodies) => bodies.findLast(kindOf) !== undefined && kindOf(bodies.findLast(kindOf)) === "問い";

// 完了の条件のうちチェックの無いもの（本文のチェックは完了の条件にだけ使う）と、チェックの欄の全部。
const boxes = (body) => [...bodyRest(body).matchAll(/^\s*- \[([ x])\] (.+)$/gm)].map((m) => ({ done: m[1] === "x", text: m[2] }));
export const remaining = (body) => boxes(body).filter((b) => !b.done).map((b) => b.text);

// 事実からステータスを決める（docs/conventions/flow.md「ステータスと割り当て」）。f は事実:
// state・status（今のステータス）・holder（動いている担当の種類か null）・unhold（ユーザーが保留から出した・答えで続けた）・released（担当の
// 実行の終わりで決める）・adopt（入口で採否を問う）・asked（答えの無い問い）・pr（作業ブランチの開いた PR: { draft, ci（pending・pass・fail）,
// demoted（CI が終わったあとに下書きへ戻された） } か null）・merged（マージした PR がある）・body・blocked（開いた前提）・start（着手可能日時）・now。
// 返すのは { status, ask（ゲートが出す問いの種類）, close（完成で閉じる）, ready（PR をレビュー可能にする） }。
export function decide(config, f) {
  const S = config.status;
  if (f.state !== "OPEN") return { status: S.done };
  if (f.holder) return { status: f.holder === "作る" ? S.working : S.review };
  if (f.status === S.hold && !f.unhold) return { status: S.hold };
  if (f.adopt) return { status: S.waiting, ask: "採否" };
  if (f.asked) return { status: S.waiting };
  if (f.pr && !f.pr.draft) return { status: S.ready };
  if (f.pr) return f.pr.ci === "pending" ? { status: S.ci } : f.pr.ci === "pass" && !f.pr.demoted ? { status: S.ready, ready: true } : { status: S.todo };
  const all = boxes(f.body);
  const left = all.filter((b) => !b.done).map((b) => b.text);
  if (all.length && !left.length) return { status: S.done, close: "COMPLETED" };
  if (left.length && left.every((l) => l.startsWith(config.userCheck))) return { status: S.waiting, ask: "確かめ" };
  if (f.blocked || startWaits(f.start, f.now)) return { status: S.todo };
  return f.released && !f.merged ? { status: S.waiting, ask: "イレギュラー" } : { status: S.todo };
}

// 節の形（PR の本文・問いの判断材料）: 節は、行の頭の「<名前>:」（「**<名前>**:」も）から次の節の頭の前まで。名前は
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
  const named = got.filter((s) => s.name);
  const order = named.map((s) => s.name);
  if (order.join("・") !== names.join("・")) problems.push(`節は「${names.join("・")}」をこの順に1つずつ置く（本文の節: 「${order.join("・")}」）`);
  for (const s of named) {
    if (!s.text) problems.push(`節「${s.name}:」が空`);
    else if (s.text === want.find((w) => w.name === s.name).text) problems.push(`節「${s.name}:」がテンプレートのまま`);
  }
  return problems;
}

// 担当の問い（判断）の誤り（無ければ空）: 行の並びは parseQuestion、判断材料は形（tools/flow-gate/question_template.md。設定の questionTemplate）の節。
export function checkQuestion(template, text) {
  const question = parseQuestion(text);
  return question?.kind === "判断" ? checkBody(parseQuestion(template).material, question.material)
    : ["「## 問い（判断）」・問いの文（1行）・「### 案」と1行1案・<details> の判断材料のほかに行がある（か、判断の問いでない）"];
}

// 問い（.claude/skills/ask/SKILL.md「問い」）: 「## 問い（種類）」の行・問いの文1行・（あれば）「### 案」と1行1案・（あれば）<details> の
// 判断材料だけ。ほかの行があれば形に合わないので null。
export function parseQuestion(text) {
  const all = normalize(text);
  const cut = all.indexOf("<details>");
  const [first, ...lines] = (cut < 0 ? all : all.slice(0, cut)).split("\n");
  const kind = QUESTION.exec(first.trim())?.[1] ?? (QUESTION.test(first.trim()) ? "判断" : null);
  if (!KINDS.includes(kind)) return null;
  const [question, header, ...plans] = lines.map((l) => l.trim()).filter(Boolean);
  if (!question || /^(#|- )/.test(question)) return null;
  if (header !== undefined && (header !== "### 案" || !plans.length || plans.some((l) => !l.startsWith("- ")))) return null;
  const material = cut < 0 ? "" : (/^<details>\s*<summary>[^<]*<\/summary>([\s\S]*?)<\/details>/.exec(all.slice(cut))?.[1].trim() ?? "");
  return { kind, text: question, plans: plans.map((l) => l.slice(2).trim()), material };
}

// ゲートが出す問い（種類ごとの文と判断材料）。
export function gateQuestion(kind, { url, conclusion } = {}) {
  const text = { 採否: "このタスクをやるか", 確かめ: "完成にしてよいか（確かめる項目は本文の完了の条件の「確かめる」の行）",
    イレギュラー: `担当の実行が、PR も問いも出さずに終わった（結果: ${conclusion}）` }[kind];
  return `## 問い（${kind}）\n${text}${url ? `\n\n<details><summary>何が起きたか</summary>\n\n実行: ${url}\n\n担当の最後の発言は、直前の「担当の終わり」のコメント。\n</details>` : ""}`;
}

// 答えのコメント（問いのコメントの後ろに続く）。good・bad は確かめの項目（bad は { item, why }）。
const oneLine = (s) => String(s).replace(/\s+/g, " ").trim();
export const answerBody = ({ question, plan, decision, good = [], bad = [], note }) =>
  ["## 回答", `**${question.text}**`, "", `決定: ${decision}`, ...(plan ? [`回答: ${plan}`] : []), ...good.map((g) => `- よい: ${g}`),
    ...bad.flatMap((b) => [`- よくない: ${b.item}`, `  - ${oneLine(b.why)}`]), ...(note ? [`補足: ${note}`] : [])].join("\n");

// 答えのコメントを読む（決定の無いものは null）。
export function parseAnswer(text) {
  const lines = normalize(text).split("\n");
  const decision = lines[0] === "## 回答" && /^決定: (\S+)$/.exec(lines.find((l) => l.startsWith("決定: ")) ?? "")?.[1];
  if (!decision) return null;
  const good = lines.filter((l) => l.startsWith("- よい: ")).map((l) => l.slice(6));
  const bad = lines.flatMap((l, i) => (l.startsWith("- よくない: ") ? [{ item: l.slice(8), why: lines[i + 1]?.replace(/^\s+- /, "") ?? "" }] : []));
  return { decision, good, bad };
}

// 答えを本文へ写す: よい項目にチェックを付け、よくない項目ごとに「直す」の行を完了の条件の最後のチェックの行のあとへ足す。
export function takeAnswer(body, { good, bad }) {
  const out = normalize(body).replace(/^(\s*- )\[ \] (.+)$/gm, (line, head, text) => (good.includes(text) ? `${head}[x] ${text}` : line));
  const fixes = bad.map((b) => `- [ ] 直す: ${b.why}`).filter((l) => !out.includes(l)).join("\n"); // 同じ答えを2度受けても重ねない
  if (!fixes) return out;
  const last = [...out.matchAll(/^\s*- \[[ x]\] .+$/gm)].at(-1);
  return last ? `${out.slice(0, last.index + last[0].length)}\n${fixes}${out.slice(last.index + last[0].length)}` : `${out}\n\n${fixes}`;
}

// 担当のワークフローの実行の名前（run-name）は「#<番号> <種類>」。
export const runOf = (title) => (/^#(\d+) (\S+)$/.exec(title ?? "") ?? []).slice(1);

// 回答フォームへのボタンの画像（GitHub の画面にはボタンを足せないので、本文の先頭にリンク付きの画像として置く）。
export const BUTTON_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" width="152" height="44" viewBox="0 0 152 44"><rect width="152" height="44" rx="8" fill="#1f6feb"/>` +
  `<text x="76" y="28" text-anchor="middle" font-size="17" font-weight="700" fill="#fff" ` +
  `font-family="system-ui,-apple-system,'Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif">回答する</text></svg>`;
