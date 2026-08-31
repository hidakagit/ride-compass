import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

const BACKEND_PATH = "/api/admin/axis-definitions";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}

export async function POST(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
