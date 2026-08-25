import { proxyToAxisAdmin } from "@/lib/adminApiProxy";

// Next.js 16ではdynamic route paramsがPromiseになった（frontend/AGENTS.md参照）。
type Params = { params: Promise<{ axisId: string }> };

export async function PUT(request: Request, { params }: Params) {
  const { axisId } = await params;
  return proxyToAxisAdmin(request, `/api/admin/axis-definitions/${encodeURIComponent(axisId)}`);
}

export async function DELETE(request: Request, { params }: Params) {
  const { axisId } = await params;
  return proxyToAxisAdmin(request, `/api/admin/axis-definitions/${encodeURIComponent(axisId)}`);
}
