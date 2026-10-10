// タスクを持つ印（docs/conventions/flow.md「1つのタスクを触るのは1者だけ」）。印は置き場の git の参照 <coordinator.holdRef><番号> で、
// 指すコミットの1行目が持ち主（開発機の対話のセッションは「開発機 <合言葉>」、担当は「<種類> <実行の URL>」）。
// 持つのは参照を作る押し込みで、参照がもうあれば断られる: 押し込みは、受ける側が参照の今の値を押し込む側の見た前の値と照らしてから
// 書く（git の文書 gitprotocol-pack の receive-pack）。毎回親の無い新しいコミットを押すので、見た値が今の値と合っていても、前へ
// 進める押し込みにならずに断られる。ラベル・コメント・Project の欄は、書いた直後の読みに書き込みが見える保証が公式の文書に無いので使わない。
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readTask, waitsOf } from "./github.js";
import { moveTask } from "./move.js";
import { notes, waitsFor } from "./rules.js";

const LOCAL = "refs/hold/";

// 印を読み書きする相手（url）と、それを打つ一時の裸のリポジトリ。token があれば、URL に入れずに要求の頭で渡す（失敗の文言に出さない）。
export function holdRemote(url, token) {
  const dir = mkdtempSync(join(tmpdir(), "flow-hold-"));
  const auth = token ? ["-c", `http.extraHeader=Authorization: Basic ${Buffer.from(`x-access-token:${token}`).toString("base64")}`] : [];
  const git = (args, input = "") => new Promise((resolve, reject) => {
    const p = spawn("git", ["-c", "user.name=flow-gate", "-c", "user.email=flow-gate@invalid", ...auth, "-C", dir, ...args]);
    let stdout = "";
    let stderr = "";
    p.stdout.on("data", (d) => (stdout += d));
    p.stderr.on("data", (d) => (stderr += d));
    p.on("error", reject);
    p.on("close", (status) => resolve({ status, stdout: stdout.trim(), stderr: stderr.trim() }));
    p.stdin.end(input);
  });
  return { url, git, ready: git(["init", "-q", "--bare"]) };
}

async function run(remote, args, input) {
  await remote.ready;
  const r = await remote.git(args, input);
  if (r.status !== 0) throw new Error(`git ${args[0]} が失敗した: ${r.stderr.split("\n").at(-1)}`);
  return r.stdout;
}

const refOf = (config, number) => `${config.coordinator.holdRef}${number}`;

// 今ある印の全部（{ number, sha, who }）。読めなければ落ちる。
export async function readHolds(remote, config) {
  await run(remote, ["fetch", "-q", "--prune", "--no-tags", remote.url, `+${config.coordinator.holdRef}*:${LOCAL}*`]);
  const lines = await run(remote, ["for-each-ref", "--format=%(refname:lstrip=2)\t%(objectname)\t%(contents:subject)", LOCAL]);
  return lines.split("\n").filter(Boolean).map((l) => {
    const [number, sha, who] = l.split("\t");
    return { number: Number(number), sha, who };
  });
}
const holdOf = async (remote, config, number) => (await readHolds(remote, config)).find((h) => h.number === Number(number)) ?? null;

// 印が sha を指しているときだけ消す（前の値つきの消去。ほかの者の印・もう無い印には何もしない）。消えたか（もう sha を指していないか）を
// 返す: 消去が通ればそれで消えたとし、断られたか応答が失われたときだけ読み直して見る。
async function drop(remote, config, number, sha) {
  await remote.ready;
  const pushed = await remote.git(["push", "--porcelain", `--force-with-lease=${refOf(config, number)}:${sha}`, remote.url, `:${refOf(config, number)}`]);
  return pushed.status === 0 || (await holdOf(remote, config, number))?.sha !== sha;
}

// 持ち主 who として持つ。持てたかは、押し込みの結果ではなく読み直して自分の印が付いていることで決める（押し込みの応答が途中で
// 失われても取り違えない）。持てなければ { held: false, by（今の持ち主。読めなければ null）, left（自分の印を消しきれなかったら、その印の
// コミット） } で、自分の印は消してから返す。
export async function take(remote, config, number, who) {
  const tree = await run(remote, ["mktree"], "");
  const sha = await run(remote, ["commit-tree", tree, "-m", who, "-m", randomUUID()]);
  await remote.git(["push", "--porcelain", remote.url, `${sha}:${refOf(config, number)}`]);
  const now = await holdOf(remote, config, number).catch(() => undefined);
  if (now?.sha === sha) return { held: true };
  const gone = await drop(remote, config, number, sha).catch(() => false);
  return { held: false, by: now?.who ?? null, ...(gone ? {} : { left: sha }) };
}

// 持ち主 who の印を手放す。何度打っても同じ結果になる: 印が無ければ手放したとし、ほかの者の印なら消さずに { released: false, by } を返す。
export async function release(remote, config, number, who) {
  const now = await holdOf(remote, config, number);
  if (!now) return { released: true };
  if (now.who !== who) return { released: false, by: now.who };
  if (!(await drop(remote, config, number, now.sha))) throw new Error(`#${number} の印を消せなかった`);
  return { released: true };
}

// 開発機の対話のセッションの持ち主の名前。合言葉は、別のセッションの印を手放さないためのもの。
export const devHolder = (word = randomUUID().slice(0, 8)) => `開発機 ${word}`;
// 担当の持ち主の名前と、そこから実行の URL を読む（担当の印でなければ null）。
export const workerHolder = (kind, url) => `${kind} ${url}`;
export const runUrlOf = (config, who) => {
  const [kind, url] = who.split(" ");
  return Object.keys(config.coordinator.slots).includes(kind) ? url : null;
};

// 担当の引き受け（bin/claim.js）。先に印を取り、取れたらタスクを読み直して、待つ理由（rules.js: waitsFor）が無く、作るなら未着手 →
// 進行中へ動かせたとき、確かめるなら検証中のときだけ、issue に着手を書いて引き受ける。引き受けなければ印を手放してから、理由で落ちる
// （手放しも落ちたら、実行が終わったあとに見回りが消す。src/dispatch.js: staleHolds）。
export async function claim(gh, remote, config, number, kind, url) {
  const who = workerHolder(kind, url);
  const got = await take(remote, config, number, who);
  if (!got.held) throw new Error(`持つ印を取れなかった（持ち主: ${got.by ?? "読めない"}）`);
  try {
    const { issue } = await readTask(gh, config, { number });
    const waits = issue && waitsFor(config, waitsOf(config, issue));
    if (waits) throw new Error(`${waits}がある`);
    const start = notes.start(kind, url);
    if (kind === "作る") return await moveTask(gh, config, number, config.working, { comment: start });
    if (issue?.status !== config.review) throw new Error("検証中ではない");
    await gh.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body: start });
    return `#${number}: ${config.review}のまま着手を書いた`;
  } catch (e) {
    await release(remote, config, number, who).catch(() => {});
    throw e;
  }
}
