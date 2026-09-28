// Claude の番（hidakagit-bot に割り当て）のタスクを、司令塔が振り出す順に並べて出す。
// 並び: 採否待ち・回答待ち（Claude に戻った問い。「その他」で答えた採否や、形の崩れた問い）→ 検証中 → 未着手。それぞれの中は「優先」のラベルがあるもの → 番号の若い順。前提が閉じていない未着手には印を付ける。
// 検証中のうち作業ブランチ（orch/tasks-<番号>）の先端が master に入ったものには、その master の CI の結果（成功・失敗・待ち）を付ける。
// 使い方: node tools/flow-gate/bin/queue.js [--json]（コードのリポジトリの作業ツリーの中で打つ）
import { execFileSync } from "node:child_process";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { botToken, userEnv } from "./token.js";

const ORDER = ["採否待ち", "回答待ち", "検証中", "未着手"];
const bot = config.people["hidakagit-bot"].node;
const gh = new GitHub(botToken());
const q = `query Queue($o: String!, $n: Int!, $field: String!, $c: String) { organization(login: $o) { projectV2(number: $n) {
  items(first: 100, after: $c) { pageInfo { hasNextPage endCursor } nodes {
    fieldValueByName(name: $field) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { ... on Issue { number title url state parent { number } assignees(first: 5) { nodes { id } } labels(first: 20) { nodes { name } }
      blockedBy(first: 50) { nodes { number state stateReason } } } } } } } } }`;
const items = [];
for (let c = null; ; ) {
  const d = await gh.gql(q, { o: config.project.owner, n: config.project.number, field: config.project.statusField, c });
  const page = d.organization.projectV2.items;
  items.push(...page.nodes);
  if (!page.pageInfo.hasNextPage) break;
  c = page.pageInfo.endCursor;
}
const tasks = items
  .map((i) => ({ ...i.content, status: i.fieldValueByName?.name }))
  .filter((t) => t.number && t.state === "OPEN" && !t.parent && ORDER.includes(t.status) && t.assignees.nodes.some((a) => a.id === bot))
  .map((t) => ({
    number: t.number,
    status: t.status,
    title: t.title,
    url: t.url,
    priority: t.labels.nodes.some((l) => l.name === "優先"),
    waitingFor: t.blockedBy.nodes.filter((b) => !(b.state === "CLOSED" && b.stateReason === "COMPLETED")).map((b) => b.number),
  }))
  .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || b.priority - a.priority || a.number - b.number);

const checking = tasks.filter((t) => t.status === "検証中");
if (checking.length) {
  const git = (...args) => execFileSync("git", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  git("fetch", "-q", "origin", "master");
  const tips = new Map(
    git("ls-remote", "origin", "refs/heads/orch/tasks-*")
      .split("\n")
      .map((line) => /^(\w+)\trefs\/heads\/orch\/tasks-(\d+)$/.exec(line))
      .filter(Boolean)
      .map(([, sha, n]) => [Number(n), sha]),
  );
  const repo = /github\.com[/:](.+?)(?:\.git)?$/.exec(git("remote", "get-url", "origin"))[1];
  for (const t of checking) {
    const sha = tips.get(t.number);
    try {
      if (!sha) continue;
      git("merge-base", "--is-ancestor", sha, "origin/master");
    } catch {
      continue;
    }
    // コードのリポジトリは hidakagit のもので、hidakagit-bot のトークンは届かない。読むだけなので hidakagit のトークンを使う。
    const res = await fetch(`https://api.github.com/repos/${repo}/actions/runs?head_sha=${sha}&branch=master`, {
      headers: { Authorization: `Bearer ${userEnv("GH_TOKEN")}`, Accept: "application/vnd.github+json" },
    });
    if (!res.ok) throw new Error(`CI の結果を読めませんでした（${res.status}）`);
    const runs = (await res.json()).workflow_runs;
    const failed = runs.filter((r) => r.status === "completed" && !["success", "skipped", "neutral"].includes(r.conclusion));
    const ci = failed.length ? "失敗" : runs.length && runs.every((r) => r.status === "completed") ? "成功" : "待ち";
    t.landed = { sha, ci, failed: failed.map((r) => r.html_url) };
  }
}

if (process.argv.includes("--json")) console.log(JSON.stringify(tasks, null, 2));
else if (!tasks.length) console.log("Claude の番のタスクは無い");
else
  for (const t of tasks)
    console.log(
      `#${t.number} ${t.status}${t.landed ? `（master に入った。CI ${t.landed.ci}）` : ""}${t.priority ? " 優先" : ""}` +
        `${t.waitingFor.length ? ` 前提待ち（${t.waitingFor.map((n) => `#${n}`).join("・")}）` : ""} ${t.title}`,
    );
