import { InboxIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { auth } from "@/auth";
import { EmptyState } from "@/components/empty-state";
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
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-10">
      <section className="surface dot-grid relative overflow-hidden px-6 py-10 sm:px-10">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/[0.07] via-transparent to-transparent" />
        <div className="relative max-w-2xl space-y-4">
          <span className="inline-flex items-center gap-2 rounded-full border bg-background/80 px-3 py-1 text-xs font-medium text-muted-foreground">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500/60" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
            Live from public government portals
          </span>
          <h1 className="text-3xl font-semibold leading-tight sm:text-4xl">
            Government tenders your business can <span className="text-primary">actually</span> bid on
          </h1>
          <p className="text-muted-foreground sm:text-lg">
            Tenders matched to your MSME, with a clause-by-clause eligibility check. Every finding cites the clause
            and page in the tender document, so you can verify it yourself.
          </p>
          {!session && (
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="lg" nativeButton={false} render={<Link href="/login?next=/onboarding" />}>
                <SparklesIcon />Match my company
              </Button>
              <Button size="lg" variant="outline" nativeButton={false} render={<Link href="#tenders" />}>Browse tenders</Button>
            </div>
          )}
        </div>
        <dl className="relative mt-8 grid max-w-2xl grid-cols-3 gap-4 border-t pt-6">
          {[
            [String(tenders.total), "live tenders"],
            [String(meta.industries.length), "industries tracked"],
            ["100%", "findings cited"],
          ].map(([value, label]) => (
            <div key={label}>
              <dt className="text-2xl font-semibold tabular-nums">{value}</dt>
              <dd className="text-xs text-muted-foreground">{label}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section id="tenders" className="scroll-mt-24 space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">Open tenders</h2>
            <p className="text-sm text-muted-foreground">
              {tenders.total} live tender{tenders.total === 1 ? "" : "s"} · soonest deadline first
            </p>
          </div>
        </div>
        <Suspense>
          <TenderFilters states={meta.states} industries={meta.industries} />
        </Suspense>

        {tenders.items.length === 0 ? (
          <EmptyState icon={InboxIcon} title="No live tenders match these filters"
                      description="Tenders appear here once their documents are uploaded and indexed. Try clearing a filter." />
        ) : (
          <div className="grid gap-3">
            {tenders.items.map((t) => <TenderCard key={t.id} tender={t} industries={meta.industries} />)}
          </div>
        )}

        {pages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-2">
            <Button variant="outline" size="sm" disabled={page <= 1} nativeButton={false} render={<Link href={pageHref(page - 1)} />}>
              Previous
            </Button>
            <span className="text-sm tabular-nums text-muted-foreground">Page {page} of {pages}</span>
            <Button variant="outline" size="sm" disabled={page >= pages} nativeButton={false} render={<Link href={pageHref(page + 1)} />}>
              Next
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}
