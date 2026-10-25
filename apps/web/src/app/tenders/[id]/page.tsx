import { ArrowLeftIcon, ExternalLinkIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { auth } from "@/auth";
import { TenderWorkspace } from "@/components/tender/workspace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UploadButton } from "@/components/upload-button";
import { closesIn, formatDate, formatDateTime, formatInr, industryName } from "@/lib/format";
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
    <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section className="space-y-5">
        <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/" />}><ArrowLeftIcon />All tenders</Button>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {tender.industries.map((i) => <Badge key={i} variant="secondary">{industryName(i, meta.industries)}</Badge>)}
            <Badge variant="outline">{closesIn(tender.closes_at)}</Badge>
          </div>
          <h1 className="text-xl font-semibold leading-snug">{tender.title}</h1>
          <p className="text-sm text-muted-foreground">{tender.org_name}</p>
        </div>
        {tender.summary && <p className="text-sm leading-relaxed">{tender.summary}</p>}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border p-4 text-sm">
          {facts.map(([k, v]) => (
            <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>
          ))}
        </dl>
        {tender.events.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-sm font-medium">Timeline</h2>
            <ol className="space-y-1.5 border-l pl-4 text-sm">
              {tender.events.map((e, i) => (
                <li key={i}>
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
