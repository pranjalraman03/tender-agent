"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangleIcon, CheckCircle2Icon, CircleHelpIcon, Loader2Icon, ShieldCheckIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { Citation } from "@/components/tender/citation";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { formatDateTime, STATUS_LABEL, VERDICT_LABEL } from "@/lib/format";
import type { Report } from "@/lib/types";

const STATUS_STYLE: Record<string, { icon: typeof CheckCircle2Icon; className: string }> = {
  met: { icon: CheckCircle2Icon, className: "text-emerald-600 dark:text-emerald-400" },
  exempt: { icon: ShieldCheckIcon, className: "text-sky-600 dark:text-sky-400" },
  not_met: { icon: XCircleIcon, className: "text-red-600 dark:text-red-400" },
  unclear: { icon: CircleHelpIcon, className: "text-amber-600 dark:text-amber-400" },
};

const VERDICT_STYLE: Record<string, string> = {
  eligible: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  possibly_eligible: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  not_eligible: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  needs_review: "bg-muted text-foreground",
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  return <Badge className={`${VERDICT_STYLE[verdict] ?? ""} border-0`}>{VERDICT_LABEL[verdict] ?? verdict}</Badge>;
}

type Status = { status: string | null; last_error: string | null; llm_configured: boolean };

export function ReportPanel({ tenderId, hasProfile }: { tenderId: number; hasProfile: boolean }) {
  const qc = useQueryClient();
  const report = useQuery({
    queryKey: ["report", tenderId],
    retry: false,
    queryFn: async () => {
      try {
        return await api<Report>(`/reports/${tenderId}`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });
  const status = useQuery({
    queryKey: ["report-status", tenderId],
    queryFn: () => api<Status>(`/reports/${tenderId}/status`),
    refetchInterval: (q) => (["queued", "running"].includes(q.state.data?.status ?? "") ? 3000 : false),
  });
  const running = ["queued", "running"].includes(status.data?.status ?? "");
  useEffect(() => {
    if (status.data?.status === "done") void qc.invalidateQueries({ queryKey: ["report", tenderId] });
  }, [status.data?.status, qc, tenderId]);
  const check = useMutation({
    mutationFn: () => api(`/reports/${tenderId}/check`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-status", tenderId] }),
  });

  if (!hasProfile) {
    return (
      <EmptyState title="Confirm your company profile first"
                  body="The eligibility check compares this tender's criteria with your confirmed profile.">
        <Button render={<Link href="/onboarding" />}>Set up profile</Button>
      </EmptyState>
    );
  }
  if (report.isLoading) return <div className="space-y-3 p-4"><Skeleton className="h-8 w-48" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>;

  const data = report.data;
  const clauseById = new Map((data?.clauses ?? []).map((c) => [c.id, c]));
  return (
    <div className="space-y-4 p-4">
      {status.data && !status.data.llm_configured && (
        <Alert>
          <AlertTriangleIcon />
          <AlertTitle>Eligibility checks are paused</AlertTitle>
          <AlertDescription>The Claude API key isn’t configured yet. Checks wait in the queue and run once it is.</AlertDescription>
        </Alert>
      )}
      {!data ? (
        <EmptyState title="No eligibility report yet"
                    body="Run a clause-by-clause check of this tender against your confirmed company profile.">
          <Button onClick={() => check.mutate()} disabled={running || check.isPending}>
            {running ? <><Loader2Icon className="animate-spin" />Checking…</> : "Check my eligibility"}
          </Button>
          {status.data?.status === "dead" && <p className="text-sm text-destructive">The last check failed. Try again.</p>}
        </EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <VerdictBadge verdict={data.verdict} />
            <span className="text-xs text-muted-foreground">
              Profile v{data.profile_version} · {formatDateTime(data.created_at)}
            </span>
            {(data.stale || data.verdict === "needs_review") && (
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => check.mutate()} disabled={running}>
                {running ? <Loader2Icon className="animate-spin" /> : null}
                {data.stale ? "Re-check with latest profile" : "Run again"}
              </Button>
            )}
          </div>
          <ul className="space-y-3">
            {data.findings.map((f) => {
              const style = STATUS_STYLE[f.status] ?? STATUS_STYLE.unclear;
              const Icon = style.icon;
              return (
                <li key={f.criterion_id} className="rounded-lg border p-3">
                  <div className="flex items-start gap-2">
                    <Icon className={`mt-0.5 size-4 shrink-0 ${style.className}`} />
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="font-medium">{f.criterion}</span>
                        <span className={`text-xs font-medium ${style.className}`}>{STATUS_LABEL[f.status] ?? f.status}</span>
                      </div>
                      <p className="text-sm text-muted-foreground">{f.note}</p>
                      <div className="flex flex-wrap">
                        {f.clause_ids.map((id) => {
                          const c = clauseById.get(id);
                          return c ? <Citation key={id} clause={c} /> : null;
                        })}
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-muted-foreground">
            Every finding cites the clause it is based on. Automated checks can be wrong — read the cited clauses before bidding.
          </p>
        </>
      )}
    </div>
  );
}

function EmptyState({ title, body, children }: { title: string; body: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-8 text-center">
      <h3 className="font-medium">{title}</h3>
      <p className="max-w-sm text-sm text-muted-foreground">{body}</p>
      {children}
    </div>
  );
}
