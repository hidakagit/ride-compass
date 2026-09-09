/**
 * APIリクエストのタイムアウト。
 *
 * 値そのものより「どの種類の待ち時間か」が本体で、同じ性質の呼び出しは必ず同じ定数を使う。
 * とくに管理画面の重い集計は、**ブラウザ側のクライアントとNext.jsのroute handler
 * （backendへの転送）が同じ値を共有する**——別々の定数にすると、片方だけ延ばしても
 * もう片方が先に打ち切って症状が変わらない。
 */

/** 既定。ユーザー操作に対して同期的に返ってくることを期待する呼び出し全般。 */
export const DEFAULT_API_TIMEOUT_MS = 15000;

/** 稼働状況の確認系。応答が無いこと自体が答えになるため、短く打ち切る。 */
export const STATUS_API_TIMEOUT_MS = 5000;

/** カタログ系（軸・材料の一覧）。画面の初期化を待たせるため既定より短くする。 */
export const CATALOG_API_TIMEOUT_MS = 10000;

/** 分布プレビュー。実データからWayを抽選して材料を組み立てるため、初回だけ時間がかかる。 */
export const DISTRIBUTION_API_TIMEOUT_MS = 60000;

/** 管理画面の全表走査を伴う集計（材料の欠損割合・派生データの鮮度台帳）。 */
export const HEAVY_ADMIN_API_TIMEOUT_MS = 90000;
