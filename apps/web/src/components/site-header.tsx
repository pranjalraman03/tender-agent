import Link from "next/link";
import { auth, signOut } from "@/auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { serverApi } from "@/lib/server-api";
import type { Me } from "@/lib/types";

async function currentMe(): Promise<Me | null> {
  const session = await auth();
  if (!session?.user?.email) return null;
  try {
    return await serverApi<Me>("/me");
  } catch {
    return null;
  }
}

export async function SiteHeader() {
  const me = await currentMe();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
            TA
          </span>
          <span>Tender Agent</span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/" />}>Tenders</Button>
          {me && <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/matches" />}>My matches</Button>}
          {me && <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/profile" />}>Company profile</Button>}
          {me?.role === "admin" && <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/admin" />}>Admin</Button>}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {me ? (
            <form
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/" });
              }}
            >
              <span className="mr-3 hidden text-sm text-muted-foreground sm:inline">{me.org.name}</span>
              <Button variant="outline" size="sm" type="submit">Sign out</Button>
            </form>
          ) : (
            <Button size="sm" nativeButton={false} render={<Link href="/login" />}>Sign in</Button>
          )}
        </div>
      </div>
    </header>
  );
}
