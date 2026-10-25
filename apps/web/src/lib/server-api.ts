import "server-only";
import { auth } from "@/auth";
import { apiToken } from "@/lib/api-token";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Server Components: call FastAPI directly, as the signed-in user when there is one. */
export async function serverApi<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await auth();
  const headers = new Headers(init?.headers);
  if (session?.user?.email) {
    headers.set("authorization", `Bearer ${await apiToken(session.user.email, session.user.name)}`);
  }
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(response.status, detail.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}
