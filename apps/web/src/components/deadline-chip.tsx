import { CalendarClockIcon } from "lucide-react";
import { closesIn, formatDateTime, urgency } from "@/lib/format";
import { cn } from "@/lib/utils";

const STYLE = {
  urgent: "bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-300",
  soon: "bg-amber-500/10 text-amber-800 ring-amber-500/25 dark:text-amber-300",
  normal: "bg-muted text-muted-foreground ring-border",
};

export function DeadlineChip({ closesAt, className }: { closesAt: string | null | undefined; className?: string }) {
  return (
    <span title={formatDateTime(closesAt)}
          className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
                        STYLE[urgency(closesAt)], className)}>
      <CalendarClockIcon className="size-3" />
      {closesIn(closesAt)}
    </span>
  );
}
