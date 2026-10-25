"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookmarkIcon, EyeOffIcon, Loader2Icon, SendIcon, WifiIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { MultiSelect } from "@/components/multi-select";
import { TenderCard } from "@/components/tender-card";
import { VerdictBadge } from "@/components/tender/report-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { FIT_LABEL } from "@/lib/format";
import type { Match, Meta } from "@/lib/types";

const FITS = [
  { value: "good", label: "Good fit" },
  { value: "possible", label: "Possible fit" },
  { value: "not_eligible", label: "Not eligible" },
];

export function MatchesList({ meta, hasProfile }: { meta: Meta; hasProfile: boolean }) {
  const qc = useQueryClient();
  const [states, setStates] = useState<string[]>([]);
  const [industries, setIndustries] = useState<string[]>([]);
  const [fits, setFits] = useState<string[]>([]);
  const [live, setLive] = useState(false);
  const query = useMemo(() => {
    const p = new URLSearchParams();
    states.forEach((s) => p.append("state", s));
    industries.forEach((i) => p.append("industry", i));
    fits.forEach((f) => p.append("fit", f));
    return p.toString();
  }, [states, industries, fits]);
  const matches = useQuery({ queryKey: ["matches", query], queryFn: () => api<Match[]>(`/matches?${query}`) });

  // Live updates: prefiltered matches appear first, then flip to agent-checked verdicts.
  useEffect(() => {
    if (!hasProfile) return;
    const source = new EventSource("/api/backend/matches/stream");
    source.addEventListener("ready", () => setLive(true));
    source.addEventListener("match", () => void qc.invalidateQueries({ queryKey: ["matches"] }));
    source.onerror = () => setLive(false);
    return () => source.close();
  }, [hasProfile, qc]);

  const setState = useMutation({
    mutationFn: ({ id, user_state }: { id: number; user_state: string | null }) =>
      api<Match>(`/matches/${id}`, { method: "PATCH", body: JSON.stringify({ user_state }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["matches"] }),
  });

  if (!hasProfile) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <h2 className="font-medium">Confirm your company profile to see matches</h2>
        <p className="mt-1 text-sm text-muted-foreground">We use it to shortlist live tenders and check eligibility.</p>
        <Button className="mt-4" render={<Link href="/onboarding" />}>Set up profile</Button>
      </div>
    );
  }

  const checking = (matches.data ?? []).filter((m) => m.stage === "prefiltered").length;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <MultiSelect label="Fit" value={fits} onChange={setFits} options={FITS} searchable={false} />
        <MultiSelect label="States" value={states} onChange={setStates} options={meta.states.map((s) => ({ value: s, label: s }))} />
        <MultiSelect label="Industries" value={industries} onChange={setIndustries}
                     options={meta.industries.map((i) => ({ value: i.slug, label: i.name }))} />
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <WifiIcon className={`size-3.5 ${live ? "text-emerald-600" : ""}`} />{live ? "Live" : "Connecting…"}
        </span>
      </div>
      {checking > 0 && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2Icon className="size-4 animate-spin" />
          {meta.llm_configured
            ? `Checking eligibility for ${checking} shortlisted tender${checking === 1 ? "" : "s"}…`
            : `${checking} shortlisted by similarity; eligibility checks start once the Claude API key is set.`}
        </p>
      )}
      {matches.isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : (matches.data ?? []).length === 0 ? (
        <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
          No matches yet. New tenders are matched as soon as they’re indexed.
        </div>
      ) : (
        <div className="grid gap-3">
          {matches.data!.map((m) => (
            <div key={m.tender.id} className="space-y-1.5">
              <TenderCard tender={m.tender} industries={meta.industries}
                aside={
                  <div className="flex flex-col items-end gap-1">
                    {m.verdict ? <VerdictBadge verdict={m.verdict} />
                      : <Badge variant="outline" className="font-normal">{m.stage === "prefiltered" ? "Shortlisted" : FIT_LABEL[m.fit ?? ""]}</Badge>}
                    {m.needs_recheck && <Badge variant="outline" className="font-normal">Corrigendum: re-checking</Badge>}
                    {m.user_state && <Badge variant="secondary" className="font-normal capitalize">{m.user_state}</Badge>}
                  </div>
                } />
              <div className="flex justify-end gap-1">
                <Button variant="ghost" size="xs" onClick={() => setState.mutate({ id: m.tender.id, user_state: m.user_state === "saved" ? null : "saved" })}>
                  <BookmarkIcon />{m.user_state === "saved" ? "Saved" : "Save"}
                </Button>
                <Button variant="ghost" size="xs" onClick={() => setState.mutate({ id: m.tender.id, user_state: m.user_state === "applying" ? null : "applying" })}>
                  <SendIcon />{m.user_state === "applying" ? "Applying" : "Mark applying"}
                </Button>
                <Button variant="ghost" size="xs" onClick={() => setState.mutate({ id: m.tender.id, user_state: "dismissed" })}>
                  <EyeOffIcon />Dismiss
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
