import { SparklesIcon } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { auth } from "@/auth";
import { TenderCard } from "@/components/tender-card";
import { TenderFilters } from "@/components/tender-filters";
import { Button } from "@/components/ui/button";
import { serverApi } from "@/lib/server-api";
import type { Meta, TenderPage } from "@/lib/types";

export default async function Home({ searchParams }: PageProps<"/">) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["state", "industry"] as const) {
    const v = sp[key];
    for (const item of Array.isArray(v) ? v : v ? [v] : []) query.append(key, item);
  }
  if (typeof sp.q === "string" && sp.q) query.set("q", sp.q);
  const page = Math.max(1, Number(sp.page ?? 1) || 1);
  query.set("page", String(page));

  const [meta, tenders, session] = await Promise.all([
    serverApi<Meta>("/meta"),
    serverApi<TenderPage>(`/tenders?${query.toString()}`),
    auth(),
  ]);
  const pages = Math.max(1, Math.ceil(tenders.total / tenders.page_size));
  const pageHref = (p: number) => {
    const next = new URLSearchParams(query);
    next.set("page", String(p));
    return `/?${next.toString()}`;
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <section className="rounded-2xl border bg-gradient-to-br from-primary/5 via-background to-background p-6 sm:p-8">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Government tenders your business can actually bid on
        </h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Live tenders from public portals, matched to your MSME. Every eligibility finding cites the clause and page
          in the tender document, so you can check it yourself.
        </p>
        {!session && (
          <div className="mt-4 flex gap-2">
            <Button render={<Link href="/login?next=/onboarding" />}><SparklesIcon />Match my company</Button>
          </div>
        )}
      </section>

      <Suspense>
        <TenderFilters states={meta.states} industries={meta.industries} />
      </Suspense>

      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">
          {tenders.total} live tender{tenders.total === 1 ? "" : "s"} · soonest deadline first
        </h2>
      </div>

      {tenders.items.length === 0 ? (
        <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
          No live tenders match these filters. Tenders appear here once their documents are indexed.
        </div>
      ) : (
        <div className="grid gap-3">
          {tenders.items.map((t) => <TenderCard key={t.id} tender={t} industries={meta.industries} />)}
        </div>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} render={<Link href={pageHref(page - 1)} />}>
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">Page {page} of {pages}</span>
          <Button variant="outline" size="sm" disabled={page >= pages} render={<Link href={pageHref(page + 1)} />}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
