import { isServer, QueryClient } from "@tanstack/react-query";

// 取り直す契機は各フックの宣言（マウント・依存の変化・`refetchInterval`）だけにする。既定の自動の再試行と
// 画面へ戻ったときの取り直しは切る——再試行は失敗の表示を数秒遅らせ、backendのレート上限（429）へ重ねて当たる。
// 取り直しは走行中のスマホでアプリを行き来するたびに通信を足す。
function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

/** 画面のデータ取得が共有するキャッシュ。フックは`useQuery(options, getQueryClient())`で渡す（Providerを置かない。
 * 描くだけのテストが包みを要らないように）。サーバーでの描画は利用者をまたいで共有しないよう毎回作る。 */
export function getQueryClient(): QueryClient {
  if (isServer) return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}
