import { handleIngestBatch } from "./queue";

export { TenantCoordinator } from "./coordinator";
export { IngestWorkflow } from "./workflow";

export default {
  async queue(batch, env, _ctx): Promise<void> {
    await handleIngestBatch(batch, env);
  },

  async fetch(request, _env, _ctx): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/health") return Response.json({ ok: true, service: "nougen-code-ingest" });
    return new Response("not found", { status: 404 });
  },
} satisfies ExportedHandler<Env, unknown>;
