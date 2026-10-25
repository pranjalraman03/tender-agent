import { ArrowLeftIcon, ExternalLinkIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { auth } from "@/auth";
import { TenderWorkspace } from "@/components/tender/workspace";
import { DeadlineChip } from "@/components/deadline-chip";
import { Button } from "@/components/ui/button";
import { UploadButton } from "@/components/upload-button";
import { formatDate, formatDateTime, formatInr, industryName } from "@/lib/format";
import { ApiError, serverApi } from "@/lib/server-api";
import type { Me, Meta, TenderDetail } from "@/lib/types";

async function load(id: string): Promise<TenderDetail> {
  if (!/^\d+$/.test(id)) notFound();
  try {
    return await serverApi<TenderDetail>(`/tenders/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}

export async function generateMetadata({ params }: PageProps<"/tenders/[id]">): Promise<Metadata> {
  const { id } = await params;
  const tender = await load(id);
  return { title: tender.title, description: tender.summary ?? undefined };
}

const EVENT_LABEL: Record<string, string> = {
  published: "Published", corrigendum: "Corrigendum issued", extended: "Deadline extended",
  cancelled: "Cancelled", awarded: "Awarded", closed: "Closed",
};

export default async function TenderPage({ params }: PageProps<"/tenders/[id]">) {
  const { id } = await params;
  const [tender, meta, session] = await Promise.all([load(id), serverApi<Meta>("/meta"), auth()]);
  const me = session?.user ? await serverApi<Me>("/me").catch(() => null) : null;
  const facts: [string, string][] = [
    ["Estimated value", formatInr(tender.value_inr)],
    ["EMD", formatInr(tender.emd_inr)],
    ["Bid deadline", formatDateTime(tender.closes_at)],
    ["Published", formatDate(tender.published_at)],
    ["Location", `${tender.work_state ?? "Not stated"}${tender.is_central ? " · Central govt" : ""}`],
    ["Reference no.", tender.reference_no ?? "—"],
    ["Portal tender ID", tender.tender_ref],
  ];

  return (
    <div className="mx-auto grid max-w-7xl gap-8 px-4 py-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section className="space-y-5">
        <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/" />}><ArrowLeftIcon />All tenders</Button>
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <DeadlineChip closesAt={tender.closes_at} />
            {tender.industries.map((i) => (
              <span key={i} className="rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-accent-foreground">
                {industryName(i, meta.industries)}
              </span>
            ))}
          </div>
          <h1 className="text-2xl font-semibold leading-snug">{tender.title}</h1>
          <p className="text-sm font-medium text-muted-foreground">{tender.org_name}</p>
        </div>
        {tender.summary && (
          <p className="border-l-2 border-primary/40 pl-3 text-sm leading-relaxed text-foreground/85">{tender.summary}</p>
        )}
        <dl className="surface grid grid-cols-2 gap-x-6 gap-y-4 p-5 text-sm">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{k}</dt>
              <dd className="mt-0.5 font-medium tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
        {tender.events.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-sm font-semibold">Timeline</h2>
            <ol className="space-y-2.5 border-l pl-5 text-sm">
              {tender.events.map((e, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-[25px] top-1.5 size-2.5 rounded-full border-2 border-background bg-primary" />
                  <span className="font-medium">{EVENT_LABEL[e.kind] ?? e.kind}</span>{" "}
                  <span className="text-muted-foreground">· {formatDate(e.detected_at)}</span>
                  {e.kind === "extended" && e.new_value?.closes_at ? (
                    <span className="text-muted-foreground"> → new deadline {formatDateTime(String(e.new_value.closes_at))}</span>
                  ) : null}
                </li>
              ))}
            </ol>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {tender.source_url && (
            <Button variant="outline" size="sm" nativeButton={false} render={<a href={tender.source_url} target="_blank" rel="noreferrer" />}>
              <ExternalLinkIcon />Portal ({tender.portal.toUpperCase()})
            </Button>
          )}
          {me && <UploadButton path={`/tenders/${tender.id}/documents`} label="Add corrigendum / document" />}
        </div>
      </section>
      <section>
        <TenderWorkspace tender={tender} signedIn={!!me} hasProfile={!!me?.has_confirmed_profile}
                         llmConfigured={meta.llm_configured} />
      </section>
    </div>
  );
}
