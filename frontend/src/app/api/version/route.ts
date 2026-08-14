import { NextResponse } from "next/server";

// プロセス（Next.jsサーバー）起動時刻。モジュール読み込み時（＝プロセス起動時）に
// 一度だけ評価される。Renderはデプロイのたびにプロセスを再起動するため、直近デプロイの
// おおよその時刻としても使える（backend/app/version.pyのSTARTED_ATと同じ考え方）。
const STARTED_AT = new Date().toISOString();

// レスポンスをビルド時に静的最適化・キャッシュさせず、リクエストのたびに評価する
// （commitは環境変数なので実質不変だが、/healthと同じ「デプロイ確認用エンドポイント」
// という性質上、常にサーバーの現在の状態を返すことを明示しておく）。
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    status: "ok",
    // RenderのWebサービス（gitリポジトリと連携したデプロイ）には`RENDER_GIT_COMMIT`
    // （デプロイされたコミットのフルSHA）が自動的に環境変数として注入される
    // （Render側の設定不要）。ローカル開発環境では未設定のためnull。
    // バックエンドの/healthと同じ確認方法: 手元のgit rev-parse HEADと比較する
    // （詳細はdocs/architecture.md「Renderデプロイの反映確認」参照）。
    commit: process.env.RENDER_GIT_COMMIT ?? null,
    started_at: STARTED_AT,
  });
}
