"use client";

import { FileTextIcon } from "lucide-react";
import { useWorkspace } from "@/components/tender/workspace-context";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ClauseOut } from "@/lib/types";

export function clauseLabel(c: ClauseOut): string {
  const pages = c.page_start === c.page_end ? `p.${c.page_start}` : `pp.${c.page_start}-${c.page_end}`;
  return c.clause_no ? `Cl. ${c.clause_no}, ${pages}` : pages;
}

/** A clickable citation: opens the PDF at the clause's page. Shows the clause text on hover. */
export function Citation({ clause }: { clause: ClauseOut }) {
  const { openClause } = useWorkspace();
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button type="button" onClick={() => openClause(clause)}
                  className="mx-0.5 inline-flex items-center gap-1 rounded-md border bg-muted/60 px-1.5 py-0.5 align-baseline text-xs font-medium text-primary hover:bg-primary/10" />
        }
      >
        <FileTextIcon className="size-3" />
        {clauseLabel(clause)}
      </TooltipTrigger>
      <TooltipContent className="max-w-sm whitespace-pre-line text-xs leading-relaxed">
        {clause.text.length > 600 ? `${clause.text.slice(0, 600)}…` : clause.text}
      </TooltipContent>
    </Tooltip>
  );
}
