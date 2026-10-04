// 開発機の対話のセッションを、担当と同じ権限の決まりで動かす。セッションの始まり（.claude/settings.json の SessionStart の
// フック）に、master の版の tools/flow-gate/settings.json から permissions.deny と autoMode をユーザー設定（~/.claude/settings.json）
// へ写す。判定役は autoMode をユーザー設定・管理者の設定・--settings からだけ読み、リポジトリの .claude/settings.json からは読まない。
// ユーザー設定のほかの項目はそのまま残す。
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { config, git } from "./cli.js";

const source = JSON.parse(git("show", `origin/${config.code.base}:tools/flow-gate/settings.json`));
const path = join(homedir(), ".claude", "settings.json");
const user = existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : {};
user.permissions = { ...user.permissions, deny: source.permissions.deny };
user.autoMode = source.autoMode;
writeFileSync(path, JSON.stringify(user, null, 2) + "\n");
