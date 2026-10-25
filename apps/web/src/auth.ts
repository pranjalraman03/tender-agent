import NextAuth, { type NextAuthConfig } from "next-auth";
import PostgresAdapter from "@auth/pg-adapter";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import Resend from "next-auth/providers/resend";
import { Pool } from "pg";

// Auth.js tables are in the `auth` schema, separate from the app's own `users` table.
const pool = new Pool({
  connectionString: process.env.AUTH_DATABASE_URL,
  options: "-c search_path=auth",
  max: 5,
});

const providers: NextAuthConfig["providers"] = [];
if (process.env.AUTH_RESEND_KEY) {
  providers.push(Resend({ apiKey: process.env.AUTH_RESEND_KEY, from: process.env.EMAIL_FROM }));
}
if (process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET) {
  providers.push(Google);
}
// Local development only: sign in with an email address, no password or email sent.
export const devLoginEnabled =
  process.env.AUTH_DEV_LOGIN === "true" && process.env.NODE_ENV !== "production";
if (devLoginEnabled) {
  providers.push(
    Credentials({
      id: "dev",
      name: "Development login",
      credentials: { email: { label: "Email", type: "email" } },
      authorize: async (credentials) => {
        const email = String(credentials?.email ?? "").trim().toLowerCase();
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return null;
        return { id: email, email, name: email.split("@")[0] };
      },
    }),
  );
}

export const providerIds = providers.map((p) => (typeof p === "function" ? p().id : p.id));

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: PostgresAdapter(pool),
  // JWT sessions: required for the dev Credentials provider, and keeps session checks
  // free of database reads. The adapter still stores users and magic-link tokens.
  session: { strategy: "jwt" },
  providers,
  pages: { signIn: "/login", verifyRequest: "/login?sent=1" },
  callbacks: {
    jwt: async ({ token, user }) => {
      if (user?.email) token.email = user.email;
      return token;
    },
    session: async ({ session, token }) => {
      if (token.email && session.user) session.user.email = token.email;
      return session;
    },
  },
});
