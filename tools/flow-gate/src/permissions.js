// 担当（Actions の Claude）へ渡す許可を、docs/conventions/flow.md に書いた操作から組み立てる。許可の一覧に合う操作は自動モードの
// 判定役を通らずに通り、合わない操作は判定役が1回ずつ可否を決める。拒否（deny）は許可より常に勝ち、許可で穴を開けられない。

// flow.md の `…` のうち、担当が打つ種類の操作。
const COMMAND = /`((?:git|gh|node) [^`\n]+)`/g;
const FETCH = /`WebFetch (https:\/\/[^`\n]+)`/g;

// 担当に決して打たせない操作。flow.md に書いてあっても許可にせず、拒否として渡す。
export const DENY = [
  "Bash(git push *master*)",
  "Bash(git push --force *)",
  "Bash(git push * --force)",
  "Bash(git push * --force *)",
  "Bash(git push -f *)",
  "Bash(git push * -f)",
  "Bash(git push * -f *)",
  "Bash(git push * +*)",
  "Bash(git reset --hard *)",
  "Bash(git clean *)",
  "Bash(git stash *)",
  "Bash(git checkout -- *)",
  "Bash(gh api * -X *)",
  "Bash(gh api * --method *)",
  "Bash(gh api * -f *)",
  "Bash(gh api * -F *)",
  "Bash(gh api * --field *)",
  "Bash(gh api * --raw-field *)",
  "Bash(gh api * --input *)",
  "Bash(gh pr merge * --admin*)",
  "Bash(gh repo *)",
  "Bash(gh secret *)",
  "Bash(gh variable *)",
  "Bash(gh workflow *)",
  "Bash(gh auth *)",
  "Bash(gh release *)",
  "Bash(gh run cancel *)",
  "Bash(gh run delete *)",
];

// 規則の `*` は任意の文字の並び。末尾の ` *` だけは、その前の語で終わる操作にも合う（公式の文書「Wildcard patterns」）。
const glob = (pattern) =>
  new RegExp(
    `^${pattern
      .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
      .replace(/ \*$/, "(?: .*)?")
      .replace(/\*/g, ".*")}$`,
    "s",
  );
const denied = (command) => DENY.some((row) => glob(row.slice(5, -1)).test(command));

// <番号> 等の置き場所は `*` にする。拒否に当たる操作は、置き場所に値を入れた形で照らす。
export function permissionsOf(flow) {
  const allow = new Set();
  for (const [, command] of flow.matchAll(COMMAND)) {
    if (!denied(command.replace(/<[^>]+>/g, "1"))) allow.add(`Bash(${command.replace(/<[^>]+>/g, "*")})`);
  }
  for (const [, url] of flow.matchAll(FETCH)) allow.add(`WebFetch(domain:${new URL(url.replace(/<[^>]+>/g, "1")).host})`);
  return { allow: [...allow].sort(), deny: DENY };
}
