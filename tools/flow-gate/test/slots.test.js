// スロットの予約（bin/slots.js）を、一時の git の置き場に作った作業ツリーで確かめる（git とディスクは本物）。道具は置き場を
// 自分の場所から引くので、一時の置き場へ写して、置き場の外の作業ディレクトリから起こす。
import assert from "node:assert/strict";
import { execFile, execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const from = (path) => fileURLToPath(new URL(path, import.meta.url));

function repo() {
  const dir = mkdtempSync(join(tmpdir(), "slots-"));
  const git = (...args) => execFileSync("git", ["-C", dir, "-c", "user.name=t", "-c", "user.email=t@example.com", ...args]);
  git("init", "-q");
  mkdirSync(join(dir, "tools", "flow-gate", "bin"), { recursive: true });
  copyFileSync(from("../bin/slots.js"), join(dir, "tools", "flow-gate", "bin", "slots.js"));
  copyFileSync(from("../flow.config.json"), join(dir, "tools", "flow-gate", "flow.config.json"));
  git("add", "tools");
  git("commit", "-q", "-m", "始め");
  for (const slot of ["a", "b"]) git("worktree", "add", "-q", "--detach", join(dir, ".claude", "worktrees", slot));
  return { dir, git, done: () => rmSync(dir, { recursive: true, force: true }) };
}

// 終了コードと出力を返す（失敗でも投げない）。
const slots = (dir, ...args) =>
  new Promise((resolve) =>
    execFile(process.execPath, [join(dir, "tools", "flow-gate", "bin", "slots.js"), ...args], { cwd: tmpdir(), encoding: "utf8" }, (e, stdout, stderr) =>
      resolve({ code: e ? e.code : 0, stdout, stderr }),
    ),
  );
const list = async (dir) => JSON.parse((await slots(dir, "--json", "a", "b")).stdout);

test("鍵を掛けたスロットは使用中になり、二人目は掛けられず、外すと空きに戻る", async () => {
  const r = repo();
  try {
    assert.equal((await slots(r.dir, "take", "a", "7", "作る")).code, 0);
    const [a, b] = await list(r.dir);
    assert.deepEqual([a.state, a.kind, a.number, a.minutes, b.state], ["使用中", "作る", 7, 0, "空き"]);
    assert.equal((await slots(r.dir, "take", "a", "8", "確かめる")).code, 1);
    assert.equal((await list(r.dir))[0].number, 7);
    r.git("worktree", "unlock", join(r.dir, ".claude", "worktrees", "a"));
    assert.equal((await list(r.dir))[0].state, "空き");
  } finally {
    r.done();
  }
});

test("起動役の pid を鍵に足すと、そのプロセスが生きているかが出る（居なくなった起動役を見分けるため）", async () => {
  const r = repo();
  try {
    assert.equal((await slots(r.dir, "take", "a", "7", "作る")).code, 0);
    assert.equal((await slots(r.dir, "pid", "a", String(process.pid))).code, 0);
    let [a] = await list(r.dir);
    assert.deepEqual([a.number, a.pid, a.alive], [7, process.pid, true]);
    assert.equal((await slots(r.dir, "pid", "a", "1")).code, 2, "pid は一度だけ足せる");
    r.git("worktree", "unlock", join(r.dir, ".claude", "worktrees", "a"));
    assert.equal((await slots(r.dir, "take", "a", "8", "確かめる")).code, 0);
    assert.equal((await slots(r.dir, "pid", "a", "999999")).code, 0);
    [a] = await list(r.dir);
    assert.deepEqual([a.number, a.alive], [8, false]);
  } finally {
    r.done();
  }
});

test("同じ番号がほかのスロットで鍵を持っていれば、掛けた鍵を外して失敗する", async () => {
  const r = repo();
  try {
    assert.equal((await slots(r.dir, "take", "a", "7", "作る")).code, 0);
    assert.equal((await slots(r.dir, "take", "b", "7", "確かめる")).code, 1);
    assert.deepEqual((await list(r.dir)).map((s) => s.state), ["使用中", "空き"]);
  } finally {
    r.done();
  }
});

test("同時に同じスロットへ掛けると、通るのは1人だけ", async () => {
  const r = repo();
  try {
    const codes = await Promise.all([1, 2, 3, 4, 5, 6].map((n) => slots(r.dir, "take", "a", String(n), "作る")));
    assert.equal(codes.filter((c) => c.code === 0).length, 1);
  } finally {
    r.done();
  }
});

test("鍵の無い枝・鍵を外したあとの変更・知らない鍵を見分け、鍵の無い枝と変更のあるスロットには鍵を掛けない", async () => {
  const r = repo();
  try {
    const a = join(r.dir, ".claude", "worktrees", "a");
    const b = join(r.dir, ".claude", "worktrees", "b");
    execFileSync("git", ["-C", a, "checkout", "-q", "-b", "orch/tasks-7"]);
    writeFileSync(join(b, "残り.txt"), "x");
    assert.deepEqual((await list(r.dir)).map((s) => s.state), ["鍵の無い枝", "未コミットの変更あり"]);
    assert.equal((await slots(r.dir, "take", "a", "8", "作る")).code, 1);
    assert.equal((await slots(r.dir, "take", "b", "8", "作る")).code, 1);
    assert.deepEqual((await list(r.dir)).map((s) => s.state), ["鍵の無い枝", "未コミットの変更あり"]);
    r.git("worktree", "lock", "--reason", "手で掛けた", a);
    const [row] = await list(r.dir);
    assert.deepEqual([row.state, row.number, row.reason], ["使用中", null, "手で掛けた"]);
  } finally {
    r.done();
  }
});
