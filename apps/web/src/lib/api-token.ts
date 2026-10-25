import "server-only";
import { SignJWT } from "jose";

const secret = new TextEncoder().encode(process.env.AUTH_SECRET ?? "");

/** Short-lived token for one call from this server to the FastAPI backend. */
export async function apiToken(email: string, name?: string | null): Promise<string> {
  return new SignJWT({ name: name ?? undefined })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(email)
    .setAudience("tender-api")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}
