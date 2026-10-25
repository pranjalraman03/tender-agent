import Link from "next/link";
import { auth, signOut } from "@/auth";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/logo";
import { MainNav } from "@/components/main-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { initials } from "@/lib/format";
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
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-4">
        <Logo />
        <MainNav items={[
          { href: "/", label: "Tenders" },
          ...(me ? [{ href: "/matches", label: "My matches" }, { href: "/profile", label: "Company" }] : []),
          ...(me?.role === "admin" ? [{ href: "/admin", label: "Admin" }] : []),
        ]} />
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {me ? (
            <form
              className="flex items-center"
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/" });
              }}
            >
              <span className="mr-3 hidden items-center gap-2 text-sm sm:inline-flex">
                <span className="grid size-6 place-items-center rounded-full bg-secondary text-[11px] font-semibold text-secondary-foreground">
                  {initials(me.org.name)}
                </span>
                <span className="max-w-40 truncate text-muted-foreground">{me.org.name}</span>
              </span>
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
