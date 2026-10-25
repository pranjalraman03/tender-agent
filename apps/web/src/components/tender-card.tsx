import { MapPinIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { DeadlineChip } from "@/components/deadline-chip";
import { formatInr, industryName, initials } from "@/lib/format";
import type { TenderCard as Tender } from "@/lib/types";

export function TenderCard({
  tender, industries, aside, href,
}: {
  tender: Tender;
  industries: { slug: string; name: string }[];
  aside?: ReactNode;
  href?: string;
}) {
  return (
    <Link href={href ?? `/tenders/${tender.id}`}
          className="surface surface-hover group relative block overflow-hidden p-5">
      <span className="absolute inset-y-0 left-0 w-0.5 bg-primary opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="flex items-start gap-4">
        <span className="hidden size-10 shrink-0 place-items-center rounded-lg bg-secondary text-xs font-semibold text-secondary-foreground sm:grid">
          {initials(tender.org_name)}
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="font-medium text-foreground/80">{tender.org_name ?? "—"}</span>
            <span className="flex items-center gap-1">
              <MapPinIcon className="size-3" />
              {tender.work_state ?? "Location not stated"}
              {tender.is_central && <span className="rounded bg-muted px-1.5 py-px text-[10px] font-medium uppercase tracking-wide">Central</span>}
            </span>
          </div>
          <h3 className="line-clamp-2 text-[15px] font-semibold leading-snug transition-colors group-hover:text-primary">
            {tender.title}
          </h3>
          {tender.summary && <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">{tender.summary}</p>}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <DeadlineChip closesAt={tender.closes_at} />
            {tender.industries.map((i) => (
              <span key={i} className="rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-accent-foreground">
                {industryName(i, industries)}
              </span>
            ))}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Value</div>
          <div className="text-base font-semibold tabular-nums">{formatInr(tender.value_inr)}</div>
          <div className="mt-1 text-xs tabular-nums text-muted-foreground">EMD {formatInr(tender.emd_inr)}</div>
          {aside && <div className="mt-3">{aside}</div>}
        </div>
      </div>
    </Link>
  );
}
