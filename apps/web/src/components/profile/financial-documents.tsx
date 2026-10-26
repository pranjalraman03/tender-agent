"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileCheck2Icon, Loader2Icon, UploadIcon } from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { ProfileState } from "@/lib/types";

type Doc = ProfileState["documents"] extends (infer D)[] | undefined ? D : never;

/** Upload CA turnover certificates; their year-by-year figures are read into the draft. */
export function FinancialDocuments({ documents, pending, compact = false }: {
  documents: Doc[];
  pending: boolean;
  /** Just the label and upload button (used in the onboarding sources box). */
  compact?: boolean;
}) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api<ProfileState>("/profile/ca-certificate", { method: "POST", body });
    },
    onSuccess: (state) => {
      qc.setQueryData(["profile"], state);
      toast.success("Certificate uploaded — reading the turnover figures…");
    },
    onError: (e) => toast.error(e.message),
  });
  const certificates = documents.filter((d) => d.kind === "ca_turnover_certificate");
  const picker = (
    <input ref={input} type="file" accept="application/pdf" hidden
           onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
  );

  if (compact) {
    return (
      <div className="space-y-2">
        <Label>CA turnover certificate (PDF)</Label>
        {picker}
        <Button variant="outline" className="w-full" disabled={upload.isPending || pending}
                onClick={() => input.current?.click()}>
          {upload.isPending || pending ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}
          {pending ? "Reading certificate…" : "Upload certificate"}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-xl text-sm text-muted-foreground">
          Upload your <span className="font-medium text-foreground">CA turnover certificate</span>. Tenders ask for
          turnover over different periods (1, 3, 5 years…), so include as many financial years as you can.
        </p>
        {picker}
        <Button variant="outline" disabled={upload.isPending || pending} onClick={() => input.current?.click()}>
          {upload.isPending || pending ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}
          {pending ? "Reading certificate…" : "Upload CA turnover certificate"}
        </Button>
      </div>
      {certificates.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {certificates.map((d) => {
            const x = d.extracted as null | { years?: string[]; rejected?: string[]; issued_by?: string | null;
                                              is_turnover_certificate?: boolean };
            return (
              <li key={d.id} className="flex items-start gap-3 px-3 py-2.5 text-sm">
                <FileCheck2Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{d.filename ?? "Certificate"}</div>
                  <div className="text-xs text-muted-foreground">
                    Uploaded {formatDate(d.uploaded_at)}
                    {x?.issued_by ? ` · ${x.issued_by}` : ""}
                    {x === null ? " · reading…"
                      : x.is_turnover_certificate === false ? " · not recognised as a turnover certificate"
                        : ` · years read: ${x.years?.join(", ") || "none"}`}
                    {x?.rejected?.length ? ` · ${x.rejected.length} figure(s) couldn’t be verified` : ""}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
