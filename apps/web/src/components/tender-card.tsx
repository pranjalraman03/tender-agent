import { Building2Icon, CalendarClockIcon, MapPinIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { closesIn, formatDateTime, formatInr, industryName, isClosingSoon } from "@/lib/format";
import type { TenderCard as Tender } from "@/lib/types";

export function TenderCard({
  tender, industries, aside, href,
}: {
  tender: Tender;
  industries: { slug: string; name: string }[];
  aside?: ReactNode;
  href?: string;
}) {
  const soon = isClosingSoon(tender.closes_at);
  return (
    <Link href={href ?? `/tenders/${tender.id}`}
          className="group block rounded-xl border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm">
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <h3 className="line-clamp-2 font-medium leading-snug group-hover:text-primary">{tender.title}</h3>
          {tender.summary && <p className="line-clamp-2 text-sm text-muted-foreground">{tender.summary}</p>}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><Building2Icon className="size-3.5" />{tender.org_name ?? "—"}</span>
            <span className="flex items-center gap-1">
              <MapPinIcon className="size-3.5" />
              {tender.work_state ?? "Location not stated"}{tender.is_central ? " · Central govt" : ""}
            </span>
            <span className={`flex items-center gap-1 ${soon ? "font-medium text-amber-600 dark:text-amber-400" : ""}`}
                  title={formatDateTime(tender.closes_at)}>
              <CalendarClockIcon className="size-3.5" />{closesIn(tender.closes_at)}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {tender.industries.map((i) => (
              <Badge key={i} variant="secondary" className="font-normal">{industryName(i, industries)}</Badge>
            ))}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-sm font-semibold">{formatInr(tender.value_inr)}</div>
          <div className="text-xs text-muted-foreground">EMD {formatInr(tender.emd_inr)}</div>
          {aside && <div className="mt-2">{aside}</div>}
        </div>
      </div>
    </Link>
  );
}
