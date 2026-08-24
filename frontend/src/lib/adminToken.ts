// 軸スタジオ（/admin、改善計画T270）の管理APIが要求するHTTP Basic認証の資格情報
// （改善計画T272）。backend/app/api/routers/axis_admin.py: require_admin_basic_authが
// 検証する値をブラウザ側で保持する。
//
// 以前（T270）は単一の「トークン」文字列だったが、T272でBasic認証（ユーザー名+パスワード）
// へ置き換えた。/adminページ本体はsrc/proxy.tsが別途Basic認証で保護しているが、
// 軸スタジオの管理API呼び出し（axisAdminApi.ts）はbackend（別オリジン）へ直接飛ぶため
// ブラウザがproxy.ts分の認証情報を自動転送してくれない——このファイルが保持する資格情報を
// axisAdminApi.tsが`Authorization: Basic ...`ヘッダとして明示的に付与する。
// 資格情報自体の妥当性はbackend側のrequire_admin_basic_authが検証する（誤った資格情報では
// APIが401を返す）ため、フロント側は「保存された資格情報をヘッダへ乗せる」役割のみを持つ。
// シングルトン＋購読の形はresearchMode.ts/debugLog.tsと同じ（useSyncExternalStoreから使う）。

export interface AdminCredentials {
  username: string;
  password: string;
}

const USERNAME_KEY = "ridecompass:admin-username";
const PASSWORD_KEY = "ridecompass:admin-password";

function loadCredentials(): AdminCredentials {
  if (typeof window === "undefined") return { username: "", password: "" };
  return {
    username: window.localStorage.getItem(USERNAME_KEY) ?? "",
    password: window.localStorage.getItem(PASSWORD_KEY) ?? "",
  };
}

let credentials: AdminCredentials = loadCredentials();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function getAdminCredentials(): AdminCredentials {
  return credentials;
}

export function setAdminCredentials(next: AdminCredentials): void {
  credentials = next;
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(USERNAME_KEY, next.username);
      window.localStorage.setItem(PASSWORD_KEY, next.password);
    } catch {
      // 保存不可は無視（次回訪問時に空へ戻るだけ）
    }
  }
  notify();
}

export function subscribeAdminCredentials(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** `Authorization: Basic ...`ヘッダの値。ユーザー名・パスワードどちらも空なら未設定として
 * nullを返す（axisAdminApi.tsがヘッダ自体を付けない判断に使う）。 */
export function adminBasicAuthHeader(): string | null {
  if (credentials.username === "" && credentials.password === "") return null;
  const encoded = btoa(`${credentials.username}:${credentials.password}`);
  return `Basic ${encoded}`;
}
