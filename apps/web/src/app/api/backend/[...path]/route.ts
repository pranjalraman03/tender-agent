import { auth } from "@/auth";
import { apiToken } from "@/lib/api-token";

// Browser -> this route -> FastAPI. The API token is minted here on the server, so it
// never reaches the browser. Bodies (uploads, SSE streams) are passed through unchanged.
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const PASS_HEADERS = ["content-type", "accept", "x-forwarded-for"];

async function forward(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = new URL(request.url);
  const target = `${API_URL}/${path.map(encodeURIComponent).join("/")}${url.search}`;
  const headers = new Headers();
  for (const name of PASS_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const session = await auth();
  if (session?.user?.email) {
    headers.set("authorization", `Bearer ${await apiToken(session.user.email, session.user.name)}`);
  }
  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    // Required by Node's fetch when streaming a request body.
    ...(hasBody ? { duplex: "half" } : {}),
    redirect: "manual",
    cache: "no-store",
  } as RequestInit);
  const out = new Headers();
  for (const name of ["content-type", "cache-control", "location", "retry-after", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { forward as GET, forward as POST, forward as PATCH, forward as PUT, forward as DELETE };
