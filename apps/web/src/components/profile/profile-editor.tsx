"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, GlobeIcon, InfoIcon, Loader2Icon, PlusIcon, Trash2Icon, UploadIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { MultiSelect } from "@/components/multi-select";
import { TagInput } from "@/components/profile/tag-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { formatDateTime, formatInr } from "@/lib/format";
import type { Me, Meta, Profile, ProfileState, ProfileUpdate, UdyamOut } from "@/lib/types";

type Project = { title: string; client?: string | null; value_inr?: number | null; year?: number | null };
type Form = {
  company_name: string; description: string; industries: string[]; states: string[]; nic_codes: string[];
  msme_category: "" | "micro" | "small" | "medium"; is_msme: boolean; annual_turnover_inr: string;
  years_in_business: string; certifications: string[]; past_projects: Project[];
};

function toForm(p: Profile, companyName: string): Form {
  return {
    company_name: companyName === "My company" ? "" : companyName,
    description: p.description ?? "", industries: p.industries, states: p.states, nic_codes: p.nic_codes,
    msme_category: (p.msme_category ?? "") as Form["msme_category"], is_msme: !!p.is_msme,
    annual_turnover_inr: p.annual_turnover_inr ? String(Number(p.annual_turnover_inr)) : "",
    years_in_business: p.years_in_business?.toString() ?? "", certifications: p.certifications,
    past_projects: (p.past_projects as Project[]) ?? [],
  };
}

function toUpdate(f: Form): ProfileUpdate {
  return {
    company_name: f.company_name || null, description: f.description || null, industries: f.industries,
    states: f.states, nic_codes: f.nic_codes, msme_category: f.msme_category || null, is_msme: f.is_msme,
    annual_turnover_inr: f.annual_turnover_inr ? Number(f.annual_turnover_inr) : null,
    years_in_business: f.years_in_business ? Number(f.years_in_business) : null,
    certifications: f.certifications,
    past_projects: f.past_projects.filter((p) => p.title.trim()).map((p) => ({
      title: p.title.trim(), client: p.client || null,
      value_inr: p.value_inr ? Number(p.value_inr) : null, year: p.year ? Number(p.year) : null,
    })),
  };
}

type Source = { source: string; url?: string; quote?: string; udyam_number?: string; error?: string };

function SourceTag({ sources }: { sources?: Source[] }) {
  if (!sources?.length) return null;
  const s = sources[sources.length - 1];
  const label = s.source === "udyam" ? "From Udyam" : s.source === "website" ? "From website" : "Edited by you";
  return (
    <Tooltip>
      <TooltipTrigger render={<span />}>
        <Badge variant="outline" className="ml-2 font-normal text-muted-foreground">{label}</Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs">
        {s.quote ? <>“{s.quote}”<br /><span className="opacity-70">{s.url}</span></>
          : s.udyam_number ? `Udyam certificate ${s.udyam_number}` : "You entered or changed this."}
      </TooltipContent>
    </Tooltip>
  );
}

function Field({ label, hint, sources, children }: { label: string; hint?: string; sources?: Source[]; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="flex items-center">{label}<SourceTag sources={sources} /></Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function ProfileEditor({ meta, me, onboarding = false }: { meta: Meta; me: Me; onboarding?: boolean }) {
  const qc = useQueryClient();
  const router = useRouter();
  const state = useQuery({
    queryKey: ["profile"],
    queryFn: () => api<ProfileState>("/profile"),
    refetchInterval: (q) => (q.state.data?.draft?.extraction_pending ? 2500 : false),
  });
  const draft = state.data?.draft ?? null;
  const confirmed = state.data?.confirmed ?? null;
  const [form, setForm] = useState<Form | null>(null);
  const [url, setUrl] = useState("");
  const udyamInput = useRef<HTMLInputElement>(null);
  const wasPending = useRef(false);

  // Load the draft into the form; reload once website extraction finishes.
  useEffect(() => {
    if (!draft) return;
    if (!form || (wasPending.current && !draft.extraction_pending)) setForm(toForm(draft, me.org.name));
    wasPending.current = draft.extraction_pending;
  }, [draft, form, me.org.name]);

  const refresh = (data: ProfileState) => qc.setQueryData(["profile"], data);
  const website = useMutation({
    mutationFn: () => api<ProfileState>("/profile/website", { method: "POST", body: JSON.stringify({ url }) }),
    onSuccess: (d) => { refresh(d); setForm(null); toast.success("Reading your website…"); },
    onError: (e) => toast.error(e.message),
  });
  const udyam = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api<UdyamOut>("/profile/udyam", { method: "POST", body });
    },
    onSuccess: async (d) => {
      toast.success(`Udyam ${d.udyam_number} read: ${d.msme_category ?? "category not found"}, NIC ${d.nic_codes.join(", ") || "—"}`);
      setForm(null);
      await qc.invalidateQueries({ queryKey: ["profile"] });
    },
    onError: (e) => toast.error(e.message),
  });
  const save = useMutation({
    mutationFn: (f: Form) => api<ProfileState>("/profile", { method: "PATCH", body: JSON.stringify(toUpdate(f)) }),
    onSuccess: (d) => { refresh(d); toast.success("Saved"); },
    onError: (e) => toast.error(e.message),
  });
  const confirm = useMutation({
    mutationFn: async (f: Form) => {
      await api<ProfileState>("/profile", { method: "PATCH", body: JSON.stringify(toUpdate(f)) });
      return api<ProfileState>("/profile/confirm", { method: "POST" });
    },
    onSuccess: (d) => {
      refresh(d);
      setForm(null);
      toast.success("Profile confirmed. Finding matching tenders…");
      router.push("/matches");
      router.refresh();
    },
    onError: (e) => toast.error(e.message),
  });
  const startEditing = useMutation({
    mutationFn: () => api<ProfileState>("/profile", { method: "PATCH", body: "{}" }),
    onSuccess: (d) => { refresh(d); setForm(null); },
  });

  if (state.isLoading) return <Loader2Icon className="mx-auto mt-20 animate-spin" />;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const sources = (draft?.field_sources ?? {}) as Record<string, Source[]>;
  const websiteError = sources._website_error?.[0]?.error;

  const starters = (
    <Card>
      <CardHeader>
        <CardTitle>{onboarding ? "Tell us about your company" : "Fill from a source"}</CardTitle>
        <CardDescription>
          We draft your profile from your website and Udyam certificate. You review every field before it’s used.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); website.mutate(); }}>
          <Label htmlFor="site">Company website</Label>
          <div className="flex gap-2">
            <Input id="site" type="url" required placeholder="https://yourcompany.in" value={url} onChange={(e) => setUrl(e.target.value)} />
            <Button type="submit" disabled={website.isPending}>{website.isPending ? <Loader2Icon className="animate-spin" /> : <GlobeIcon />}Read</Button>
          </div>
        </form>
        <div className="space-y-2">
          <Label>Udyam registration certificate (PDF)</Label>
          <input ref={udyamInput} type="file" accept="application/pdf" hidden
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) udyam.mutate(f); e.target.value = ""; }} />
          <Button variant="outline" className="w-full" disabled={udyam.isPending} onClick={() => udyamInput.current?.click()}>
            {udyam.isPending ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}Upload certificate
          </Button>
        </div>
        {!draft && (
          <Button variant="link" className="justify-start px-0 sm:col-span-2" onClick={() => startEditing.mutate()}>
            Or fill the form by hand
          </Button>
        )}
      </CardContent>
    </Card>
  );

  if (!draft) {
    return (
      <div className="space-y-6">
        {confirmed ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><CheckIcon className="text-emerald-600" />Confirmed profile v{confirmed.version}</CardTitle>
              <CardDescription>Confirmed {formatDateTime(confirmed.confirmed_at)}. Matching uses this version.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>{confirmed.description}</p>
              <p><span className="text-muted-foreground">States:</span> {confirmed.states.join(", ")}</p>
              <p><span className="text-muted-foreground">Turnover:</span> {formatInr(confirmed.annual_turnover_inr)} ·{" "}
                <span className="text-muted-foreground">MSME:</span> {confirmed.msme_category ?? (confirmed.is_msme ? "yes" : "—")}</p>
              <Button onClick={() => startEditing.mutate()} disabled={startEditing.isPending}>Edit profile</Button>
            </CardContent>
          </Card>
        ) : starters}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {starters}
      {draft.extraction_pending && (
        <Alert><Loader2Icon className="animate-spin" /><AlertDescription>Reading your website… fields will fill in automatically.</AlertDescription></Alert>
      )}
      {websiteError && <Alert variant="destructive"><AlertDescription>Couldn’t read the website: {websiteError}</AlertDescription></Alert>}
      {form && (
        <Card>
          <CardHeader>
            <CardTitle>Review your profile</CardTitle>
            <CardDescription>
              Draft v{draft.version}. Matching only uses confirmed fields — check each one, especially numbers.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5 sm:grid-cols-2">
            <Field label="Company name"><Input value={form.company_name} onChange={(e) => set("company_name", e.target.value)} /></Field>
            <Field label="Years in business" sources={sources.years_in_business}>
              <Input type="number" min={0} value={form.years_in_business} onChange={(e) => set("years_in_business", e.target.value)} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="What you do" sources={sources.description} hint="Used to find tenders with similar scope.">
                <Textarea rows={3} value={form.description} onChange={(e) => set("description", e.target.value)} />
              </Field>
            </div>
            <Field label="Industries" sources={sources.industries}>
              <MultiSelect label="Industries" value={form.industries} onChange={(v) => set("industries", v)}
                           options={meta.industries.map((i) => ({ value: i.slug, label: i.name }))} />
            </Field>
            <Field label="States you can work in" sources={sources.states}>
              <MultiSelect label="States" value={form.states} onChange={(v) => set("states", v)}
                           options={meta.states.map((s) => ({ value: s, label: s }))} />
            </Field>
            <Field label="Average annual turnover (₹)" sources={sources.annual_turnover_inr}
                   hint={form.annual_turnover_inr ? `= ${formatInr(form.annual_turnover_inr)}` : "Last three financial years"}>
              <Input type="number" min={0} value={form.annual_turnover_inr} onChange={(e) => set("annual_turnover_inr", e.target.value)} />
            </Field>
            <Field label="MSME category" sources={sources.msme_category}>
              <div className="flex items-center gap-3">
                <select className="h-9 rounded-lg border bg-background px-2 text-sm" value={form.msme_category}
                        onChange={(e) => set("msme_category", e.target.value as Form["msme_category"])}>
                  <option value="">Not specified</option><option value="micro">Micro</option>
                  <option value="small">Small</option><option value="medium">Medium</option>
                </select>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={form.is_msme} onCheckedChange={(v) => set("is_msme", v)} />Udyam-registered MSME
                </label>
              </div>
            </Field>
            <Field label="Certifications & registrations" sources={sources.certifications} hint="e.g. ISO 9001, CPWD Class IV (Electrical), NSIC">
              <TagInput value={form.certifications} onChange={(v) => set("certifications", v)} placeholder="Type and press Enter" />
            </Field>
            <Field label="NIC codes" sources={sources.nic_codes}>
              <TagInput value={form.nic_codes} onChange={(v) => set("nic_codes", v)} placeholder="e.g. 43211" />
            </Field>
            <div className="space-y-2 sm:col-span-2">
              <Label className="flex items-center">Completed projects<SourceTag sources={sources.past_projects} /></Label>
              <p className="text-xs text-muted-foreground"><InfoIcon className="mr-1 inline size-3" />Experience criteria compare against these values.</p>
              {form.past_projects.map((p, i) => (
                <div key={i} className="grid gap-2 sm:grid-cols-[2fr_1.5fr_1fr_0.7fr_auto]">
                  <Input placeholder="Project / work" value={p.title}
                         onChange={(e) => set("past_projects", form.past_projects.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} />
                  <Input placeholder="Client" value={p.client ?? ""}
                         onChange={(e) => set("past_projects", form.past_projects.map((x, j) => j === i ? { ...x, client: e.target.value } : x))} />
                  <Input placeholder="Value ₹" type="number" value={p.value_inr ?? ""}
                         onChange={(e) => set("past_projects", form.past_projects.map((x, j) => j === i ? { ...x, value_inr: e.target.value ? Number(e.target.value) : null } : x))} />
                  <Input placeholder="Year" type="number" value={p.year ?? ""}
                         onChange={(e) => set("past_projects", form.past_projects.map((x, j) => j === i ? { ...x, year: e.target.value ? Number(e.target.value) : null } : x))} />
                  <Button variant="ghost" size="icon" aria-label="Remove project"
                          onClick={() => set("past_projects", form.past_projects.filter((_, j) => j !== i))}><Trash2Icon /></Button>
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => set("past_projects", [...form.past_projects, { title: "" }])}>
                <PlusIcon />Add project
              </Button>
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t pt-4 sm:col-span-2">
              <Button variant="outline" onClick={() => save.mutate(form)} disabled={save.isPending}>Save draft</Button>
              <Button onClick={() => confirm.mutate(form)} disabled={confirm.isPending || draft.extraction_pending}>
                {confirm.isPending ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}Confirm & find tenders
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
