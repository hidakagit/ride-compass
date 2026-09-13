import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: GET /api/admin/road-graph-tiles（split済みタイルの全件、Basic認証必須）。
// 単一テーブルの読み取りのため、db-statusのような長いタイムアウトは要らない。
const BACKEND_PATH = "/api/admin/road-graph-tiles";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
