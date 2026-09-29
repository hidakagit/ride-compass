// 担当の起動役。dispatch.js が鍵を掛けたスロットで切り離して起こす。担当（claude -p）を起こし、担当のプロセスが終わった
// 瞬間に後始末をする: 作る担当が Pull Request も問いも出さずに終わった（issue が振り出した状態のまま）なら落ちたとみなして
// 保留にする → スロットに未コミットの変更が無ければ枝を手放して鍵を外す（あれば鍵ごと残す）→ 状況の更新を書く → 次の振り出し
// （dispatch.js）を起こす。担当は作業と報告だけをし、鍵・スロット・振り出しには触れない。
// 担当が持ち時間（coordinator.dropMinutes）を超えても終わらなければ、担当を止めて同じ後始末をする（生きたまま止まった担当）。
// 起動役ごと消えた（PC の再起動等）スロットは、dispatch.js が --finish で同じ後始末をする。
// 使い方: node tools/flow-gate/bin/work.js <スロット> <issue の番号> <作る|確かめる>
//         node tools/flow-gate/bin/work.js --finish <スロット> [--no-dispatch]（--no-dispatch は後始末のあと司令塔を起こさない。司令塔から呼ぶとき）
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, openSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, readTask } from "../src/github.js";
import { botToken } from "./token.js";

const here = dirname(fileURLToPath(import.meta.url));
const git = (dir, ...rest) => execFileSync("git", ["-C", dir, ...rest], { encoding: "utf8" }).trim();
const root = join(git(here, "rev-parse", "--path-format=absolute", "--git-common-dir"), "..");
const slotDir = (slot) => join(root, ".claude", "worktrees", slot);
const node = (script, ...rest) => execFileSync(process.execPath, [join(here, script), ...rest], { encoding: "utf8" }).trim();
const log = (line) => console.log(`${new Date().toISOString()} ${line}`);
// 後始末の1歩。失敗しても残りの歩（とくに状況の更新と次の振り出し）は止めず、失敗を異常として返す。
const step = (what, fn) => {
  try {
    const out = fn();
    if (out) log(out);
    return [];
  } catch (e) {
    const why = `${what}に失敗: ${String(e.stderr || e.message).trim()}`;
    log(why);
    return [why];
  }
};

const args = process.argv.slice(2);
if (args[0] === "--finish" && (args.length === 2 || (args.length === 3 && args[2] === "--no-dispatch"))) {
  const s = JSON.parse(node("slots.js", "--json", args[1]))[0];
  if (s?.state !== "使用中" || !s.number) process.exit(0);
  await finish(args[1], s.number, s.kind, "起動役が見つからない（PC の再起動や、手で止められた）", args[2] !== "--no-dispatch");
} else if (args.length === 3 && /^\d+$/.test(args[1]) && ["作る", "確かめる"].includes(args[2])) {
  const [slot, number, kind] = args;
  // pid が鍵に無いと、起動役が居なくなっても司令塔が見分けられないので、記録できなければ担当を起こさない。
  const failed = step("起動役の pid を鍵へ記録するの", () => node("slots.js", "pid", slot, String(process.pid)));
  if (failed.length) await finish(slot, Number(number), kind, "起動役の pid を鍵へ記録できなかった");
  else {
    log(`#${number} の${kind}担当を起こす（スロット ${slot}）`);
    step("状況の更新", () => node("status.js"));
    const why = await run(slot, Number(number), kind);
    await finish(slot, Number(number), kind, why);
  }
} else {
  console.error("使い方: node tools/flow-gate/bin/work.js <スロット> <issue の番号> <作る|確かめる> | --finish <スロット> [--no-dispatch]");
  process.exit(2);
}

// 担当を起こし、終わるまで待つ。持ち時間を超えたら担当を（子のプロセスごと）止める。出力はスロットごとの記録に残す
// （.claude/dispatch-logs/）。返すのは終わり方の1行。
function run(slot, number, kind) {
  const dir = slotDir(slot);
  const logs = join(root, ".claude", "dispatch-logs");
  mkdirSync(logs, { recursive: true });
  const out = openSync(join(logs, `${slot}-${number}-${Date.now()}.log`), "a");
  const prompt = [
    `あなたは RideCompass の${kind}担当です。作業ツリー ${dir} で、置き場 ${config.repository} の issue #${number} を扱います。`,
    `まず ${dir} の CLAUDE.md と docs/conventions/flow.md の「司令塔と担当」「${kind}担当」「問い」「issue の形」を読み、その手順のとおりに進めてください。`,
    "作業はこの作業ツリーの中だけで行い、終わるときは手順のとおり push と issue への報告をして終えてください。",
    "鍵・スロット・次の振り出しの後始末は起動役がするので、触れないでください。すべて日本語で書いてください。",
  ].join("\n");
  const { dropMinutes } = config.coordinator;
  return new Promise((resolve) => {
    const child = spawn("claude", ["-p", prompt, "--permission-mode", "auto", "--permission-prompts", "none"], {
      cwd: dir,
      stdio: ["ignore", out, out],
      windowsHide: true,
    });
    // 持ち時間は壁時計で測る（PC が寝ていた間も数える。鍵の経過時間と同じ物差し）。
    const start = Date.now();
    let stopped = false;
    const timer = setInterval(() => {
      if (stopped || Date.now() - start <= dropMinutes * 60000) return;
      stopped = true;
      log(`担当が持ち時間 ${dropMinutes} 分を超えたので止める`);
      // Windows で子のプロセス（claude が起こしたシェル等）まで止めるには、プロセスの木ごと止める。
      if (process.platform === "win32") step("担当を止めるの", () => execFileSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], { encoding: "utf8" }));
      else child.kill("SIGKILL");
    }, 60000);
    const end = (why) => (clearInterval(timer), resolve(stopped ? `担当が持ち時間 ${dropMinutes} 分を超えたので止めた` : why));
    child.on("error", (e) => end(`担当を起こせなかった（${e.message}）`));
    child.on("exit", (code) => end(`担当のプロセスが終了コード ${code ?? -1} で終わった`));
  });
}

// 後始末。作る担当の issue が振り出した状態（進行中）のままなら、Pull Request も問いも出さずに終わったので落ちたとみなす。
// どの歩が失敗しても、状況の更新と次の振り出しまで進める。
async function finish(slot, number, kind, why, next = true) {
  const dir = slotDir(slot);
  const found = [];
  if (kind === "作る") {
    try {
      const { issue } = await readTask(new GitHub(botToken()), config, { number });
      const doing = config.transitions.find((t) => t.on === "振り出し").to[0];
      if (issue?.state === "OPEN" && issue.status === doing) {
        const failed = step("保留へ動かすの", () =>
          node("move.js", String(number), "落ちた", `スロット ${slot} の作る担当が、Pull Request も問いも出さずに終わった（${why}）`),
        );
        found.push(failed[0] ?? `スロット ${slot} の作る担当（#${number}）が Pull Request も問いも出さずに終わったので保留にした（${why}）`);
      }
    } catch (e) {
      found.push(`#${number} のステータスを読めなかった: ${e.message}`);
    }
  }
  const dirty = (() => {
    try {
      return git(dir, "status", "--porcelain") !== "";
    } catch {
      return true;
    }
  })();
  if (dirty) found.push(`スロット ${slot}（#${number} の${kind}担当）に未コミットの変更が残っているので、鍵ごと残した（${why}）`);
  else {
    found.push(...step("枝を手放すの", () => git(dir, "checkout", "-q", "--detach")));
    // 鍵は人や前の手順の担当が先に外していることがある。
    found.push(
      ...step("鍵を外すの", () => {
        if (JSON.parse(node("slots.js", "--json", slot))[0]?.state !== "使用中") return `スロット ${slot} の鍵はもう外れていた`;
        git(dir, "worktree", "unlock", dir);
        return `スロット ${slot} の鍵を外した（${why}）`;
      }),
    );
  }
  step("状況の更新", () => node("status.js", ...found.flatMap((f) => ["--found", f])));
  if (next) step("次の振り出し", () => node("dispatch.js"));
}
