// 移行の準備（bin/migrate.js の最初の段）: コードが前提にする GitHub の設定を作って確かめる。何度打っても同じ結果になる（あれば作らない）。
// 1. Actions のボードの Status の選択肢を flow.config.json: status の並びにそろえる。updateProjectV2Field の singleSelectOptions は渡した一覧で
//    丸ごと置き換えるので、今ある選択肢は id・名前・色・説明をそのまま渡し、無いものだけ id なしで足す（id を渡せば、タスクのステータスは
//    消えない。公式の文書 GraphQL の Projects「updateProjectV2Field」「ProjectV2SingleSelectFieldOptionInput」）。前後で開いたタスクの
//    ステータスごとの数が変わらないことを確かめる。
// 2. 対話作業のボード（題名 dialog.title）が無ければ組織に作る。3. issue の種類 dialog.type が無ければ作る。
// 4. 読み直して、コードの名前と一致しているか・打った名義（hidakagit-bot）が対話作業のボードに書けるか・ゲートの App の組織のインストールが
//    要る権限と出来事を持つかを確かめる（App は組織のボードの権限で全部のボードに書く。ボードごとの割り当ては無い）。返すのは一致しないものと
//    その直し方の並び（空なら済んだ）。コードのリポジトリ側のインストール（hidakagit のアカウント）は、この名義では読めないので見ない。
import { readTasks } from "./dispatch.js";
import { dialogBoard, typeIds } from "./github.js";

const FIELD = `query Field($o: String!, $n: Int!, $f: String!) { organization(login: $o) { id projectV2(number: $n) { id
  field(name: $f) { ... on ProjectV2SingleSelectField { id options { id name color description } } } } } }`;

// ゲートの App が組織のインストールに要る権限と出来事（src/gate.js: handleEvent が受けるもの）。
const APP_PERMISSIONS = { issues: "write", organization_projects: "write", contents: "read" };
const APP_EVENTS = ["issues", "issue_comment", "projects_v2_item", "repository_dispatch"];
const MANUAL = "組織 ridecompass の Settings → GitHub Apps → ゲートの App の Configure で、権限（Repository permissions の Issues・Contents、Organization permissions の Projects）と出来事を見る";

async function appProblems(gh, config) {
  const slug = config.gate.replace(/\[bot\]$/, "");
  const list = await gh.rest("GET", `/orgs/${config.project.owner}/installations?per_page=100`).catch((e) => ({ error: e.message }));
  if (list.error) return [`ゲートの App の組織のインストールを読めない（${list.error}）: ${MANUAL}`];
  const app = list.installations.find((i) => i.app_slug === slug);
  if (!app) return [`ゲートの App（${slug}）が組織に入っていない: ${MANUAL}`];
  const level = { read: 1, write: 2 };
  const lacks = [...Object.entries(APP_PERMISSIONS).filter(([k, v]) => (level[app.permissions[k]] ?? 0) < level[v]).map(([k, v]) => `権限 ${k}: ${v}`),
    ...APP_EVENTS.filter((e) => !app.events.includes(e)).map((e) => `出来事 ${e}`)];
  return lacks.length ? [`ゲートの App の組織のインストールに足りない（${lacks.join("・")}）: ${MANUAL}`] : [];
}

const counts = async (gh, config) => {
  const out = {};
  for (const t of (await readTasks(gh, config, "is:open")).tasks) out[t.status ?? "（無し）"] = (out[t.status ?? "（無し）"] ?? 0) + 1;
  return JSON.stringify(Object.fromEntries(Object.entries(out).sort()));
};

export async function prepare(gh, config, { dry = false, say = () => {} } = {}) {
  const { owner, number, statusField } = config.project;
  const read = async () => (await gh.gql(FIELD, { o: owner, n: number, f: statusField })).organization;
  const org = await read();
  const field = org.projectV2.field;
  const want = Object.values(config.status);
  const have = field.options.map((o) => o.name);
  const order = [...want, ...have.filter((n) => !want.includes(n))]; // 設定に無い選択肢は消さずに後ろへ残す
  if (have.join() !== order.join()) {
    const options = order.map((name) => {
      const o = field.options.find((x) => x.name === name);
      return o ? { id: o.id, name, color: o.color, description: o.description ?? "" } : { name, color: "GRAY", description: "" };
    });
    say(`Status の選択肢を「${options.map((o) => o.name).join("・")}」にする（足す: ${want.filter((n) => !have.includes(n)).join("・") || "無し"}）`);
    if (!dry) {
      const before = await counts(gh, config);
      await gh.write([["updateProjectV2Field", { fieldId: field.id, singleSelectOptions: options }]]);
      const after = await counts(gh, config);
      if (before !== after) throw new Error(`Status の選択肢を変えたら、開いたタスクのステータスごとの数が変わった（前 ${before} → 後 ${after}）`);
      say(`開いたタスクのステータスごとの数は変わらない（${after}）`);
    }
  }
  // 作れなかったもの（名義の権限が足りない等）は、手で作る手順にして返す。
  const failed = [];
  const make = (what, by, call) => (dry ? undefined : call().catch((e) => failed.push(`${what}を作れなかった（${e.message}）: ${by}`)));
  if (!(await dialogBoard(gh, config))) {
    say(`対話作業のボード「${config.dialog.title}」を組織に作る`);
    await make("対話作業のボード", `組織 ${owner} の Projects → New project で、題名「${config.dialog.title}」のボードを作る`,
      () => gh.gql("mutation P($i: CreateProjectV2Input!) { createProjectV2(input: $i) { projectV2 { number } } }", { i: { ownerId: org.id, title: config.dialog.title } }));
  }
  if (!(await typeIds(gh, config))[config.dialog.type]) {
    say(`issue の種類「${config.dialog.type}」を組織に作る`);
    await make("issue の種類", `組織 ${owner} の Settings → Planning → Issue types → Create new type で「${config.dialog.type}」を作る`,
      () => gh.write([["createIssueType", { ownerId: org.id, name: config.dialog.type, isEnabled: true, description: "開発機の対話のセッションがする作業（docs/conventions/flow.md）" }]]));
  }
  // 試しでも読み直して確かめる（試しの結果は、書く前の今の状態）。
  const now = (await read()).projectV2.field.options.map((o) => o.name);
  const board = await dialogBoard(gh, config);
  return [
    ...failed,
    ...(now.slice(0, want.length).join() === want.join() ? [] : [`Status の選択肢が「${now.join("・")}」で、設定の「${want.join("・")}」と合わない`]),
    ...(!board ? [`対話作業のボード「${config.dialog.title}」が無い`] : board.viewerCanUpdate ? []
      : [`${config.claude} が対話作業のボード（${board.number}番）に書けない: ボードの ⋯ → Settings → Manage access で ${config.claude} を Write にする`]),
    ...((await typeIds(gh, config))[config.dialog.type] ? [] : [`issue の種類「${config.dialog.type}」が無い`]),
    ...(await appProblems(gh, config)),
  ];
}
