import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

type Params = { params: Promise<{ axisId: string }> };

export async function POST(request: Request, { params }: Params) {
  const { axisId } = await params;
  return proxyToBackendAdmin(request, `/api/admin/axis-definitions/${encodeURIComponent(axisId)}/unpublish`);
}
