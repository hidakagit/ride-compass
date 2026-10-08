import { NextResponse } from "next/server";

// プロセス（Next.jsサーバー）起動時刻。モジュール読み込み時（＝プロセス起動時）に
// 一度だけ評価される。Renderはデプロイのたびにプロセスを再起動するため、直近デプロイの
// おおよその時刻としても使える（backend/app/version.pyのSTARTED_ATと同じ考え方）。
const STARTED_AT = new Date().toISOString();

// レスポンスをビルド時に静的最適化・キャッシュさせず、リクエストのたびに評価する
// （commitは環境変数なので実質不変だが、/healthと同じ「デプロイ確認用エンドポイント」
// という性質上、常にサーバーの現在の状態を返すことを明示しておく）。
export const dynamic = "force-dynamic";

/** 動いている版に入っている直近の変更（新しい順。先頭は版のコミットそのもの）。 */
interface RecentChange {
  /** コミットの件名（メッセージの1行目）。 */
  subject: string;
  /** masterへ入った時刻（squashのマージではマージした時刻）。 */
  committed_at: string;
}

const RECENT_COUNT = 3;
const GITHUB_TIMEOUT_MS = 5_000;

// 件名はコミットで決まるので、版ごとに1回だけGitHubへ問い合わせる。失敗も覚え、次のデプロイ（版が変わる）まで
// 問い合わせ直さない——認証の無いGitHubのAPIは送り元のIPあたり毎時60回までで、この口はデプロイの待ち
// （deploy-frontend.yml）が30秒ごとに読むため、失敗のたびに問い合わせ直すと上限を使い切る。
// ビルドで埋め込まないのは、RenderのDockerのビルドは.gitを持たず（Renderの係の掲示板での答え。公式の文書には無い）、
// RENDER_GIT_COMMITがビルド引数として渡るかも公式の文書に無いため（実行時の環境変数は公式の文書「Environment variables」にある）。
let recentOfCommit: { commit: string; changes: Promise<RecentChange[]> } | null = null;

function recentChanges(commit: string | null, repo: string | undefined): Promise<RecentChange[]> {
  if (commit === null || !repo) return Promise.resolve([]);
  if (recentOfCommit?.commit !== commit) recentOfCommit = { commit, changes: fetchRecentChanges(repo, commit) };
  return recentOfCommit.changes;
}

async function fetchRecentChanges(repo: string, commit: string): Promise<RecentChange[]> {
  try {
    const response = await fetch(
      `https://api.github.com/repos/${repo}/commits?sha=${commit}&per_page=${RECENT_COUNT}`,
      {
        headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
        signal: AbortSignal.timeout(GITHUB_TIMEOUT_MS),
      },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const commits = (await response.json()) as { commit: { message: string; committer: { date: string } } }[];
    return commits.map(({ commit: { message, committer } }) => ({
      subject: message.split("\n", 1)[0],
      committed_at: committer.date,
    }));
  } catch (error) {
    console.warn(`直近の変更の件名をGitHubから取れなかった（版 ${commit}）`, error);
    return [];
  }
}

export async function GET() {
  // RenderのWebサービス（gitリポジトリと連携したデプロイ）には`RENDER_GIT_COMMIT`
  // （デプロイされたコミットのフルSHA）と`RENDER_GIT_REPO_SLUG`（`所有者/リポジトリ`）が自動的に
  // 環境変数として注入される（Render側の設定不要）。ローカル開発環境では未設定のためcommitはnull。
  // バックエンドの/healthと同じ確認方法: 手元のgit rev-parse HEADと比較する
  // （詳細はdocs/architecture/tech-stack.md「デプロイの反映確認」参照）。
  const commit = process.env.RENDER_GIT_COMMIT ?? null;
  return NextResponse.json({
    status: "ok",
    commit,
    started_at: STARTED_AT,
    recent: await recentChanges(commit, process.env.RENDER_GIT_REPO_SLUG),
  });
}
