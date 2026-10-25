import { LandmarkIcon } from "lucide-react";
import Link from "next/link";

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
        <LandmarkIcon className="size-4" />
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-tight">Tender Agent</span>
        <span className="block text-[11px] text-muted-foreground">Govt tenders for MSMEs</span>
      </span>
    </Link>
  );
}
