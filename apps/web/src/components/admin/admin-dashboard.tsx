"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLinkIcon, PlayIcon, RefreshCwIcon, RotateCcwIcon } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UploadButton } from "@/components/upload-button";
import { api } from "@/lib/api";
import { closesIn, formatDateTime } from "@/lib/format";
import type { AdminOverview, NeededDoc } from "@/lib/types";

export function AdminDashboard() {
  const qc = useQueryClient();
  const overview = useQuery({ queryKey: ["admin", "overview"], queryFn: () => api<AdminOverview>("/admin/overview"), refetchInterval: 10_000 });
  const needed = useQuery({ queryKey: ["admin", "needed"], queryFn: () => api<NeededDoc[]>("/admin/documents-needed") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin"] });
  const crawl = useMutation({
    mutationFn: () => api<{ queued: boolean }>("/admin/crawl/cppp", { method: "POST" }),
    onSuccess: (r) => toast.success(r.queued ? "Crawl queued" : "A crawl was already queued this minute"),
  });
  const retry = useMutation({
    mutationFn: (id: number) => api(`/admin/jobs/${id}/retry`, { method: "POST" }),
    onSuccess: () => { toast.success("Requeued"); void refresh(); },
  });

  const o = overview.data;
  const totalCost = (o?.llm_cost_7d ?? []).reduce((s, c) => s + Number(c.cost_usd ?? 0), 0);
  return (
    <div className="space-y-6">
      {o && !o.llm_configured && (
        <Alert>
          <AlertTitle>Claude API key not configured</AlertTitle>
          <AlertDescription>Indexing, eligibility checks, website extraction and chat jobs wait in the queue until ANTHROPIC_API_KEY is set (then restart the worker).</AlertDescription>
        </Alert>
      )}
      <div className="flex gap-2">
        <Button size="sm" onClick={() => crawl.mutate()}><PlayIcon />Crawl CPPP now</Button>
        <Button size="sm" variant="outline" onClick={() => void refresh()}><RefreshCwIcon />Refresh</Button>
      </div>
      <Tabs defaultValue="docs">
        <TabsList>
          <TabsTrigger value="docs">Documents needed {needed.data ? `(${needed.data.length})` : ""}</TabsTrigger>
          <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
          <TabsTrigger value="costs">LLM cost & evals</TabsTrigger>
        </TabsList>
        <TabsContent value="docs" className="space-y-3 pt-3">
          <p className="text-sm text-muted-foreground">
            CPPP serves documents only behind a captcha, which we never bypass. Open the portal, find the tender by its ID,
            download the documents yourself, and upload the PDF or ZIP here. Parsing, indexing and matching then run automatically.
          </p>
          <Card>
            <Table>
              <TableHeader>
                <TableRow><TableHead>Tender</TableHead><TableHead>Portal ID / Ref.</TableHead><TableHead>Deadline</TableHead><TableHead /></TableRow>
              </TableHeader>
              <TableBody>
                {(needed.data ?? []).map((n) => (
                  <TableRow key={n.tender_id}>
                    <TableCell className="max-w-md whitespace-normal">
                      <div className="font-medium">{n.title}</div>
                      <div className="text-xs text-muted-foreground">{n.org_name}</div>
                      {n.reason === "corrigendum" && <Badge variant="outline" className="mt-1">Corrigendum issued</Badge>}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      <div>{n.portal_tender_id}</div><div className="text-muted-foreground">{n.reference_no}</div>
                    </TableCell>
                    <TableCell className="text-sm">{closesIn(n.closes_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" render={<a href={n.portal_url} target="_blank" rel="noreferrer" />}>
                          <ExternalLinkIcon />Portal
                        </Button>
                        <UploadButton path={`/admin/tenders/${n.tender_id}/documents`} label="Upload"
                                      onDone={() => void refresh()} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {needed.data?.length === 0 && (
                  <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">Nothing waiting for documents.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>
        <TabsContent value="pipeline" className="grid gap-4 pt-3 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="text-base">Tenders</CardTitle></CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Pipeline</TableHead><TableHead>Lifecycle</TableHead><TableHead className="text-right">Count</TableHead></TableRow></TableHeader>
                <TableBody>
                  {(o?.tenders_by_status ?? []).map((t, i) => (
                    <TableRow key={i}><TableCell>{String(t.pipeline_status)}</TableCell><TableCell>{String(t.lifecycle_status)}</TableCell><TableCell className="text-right tabular-nums">{String(t.count)}</TableCell></TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Jobs</CardTitle></CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Kind</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Count</TableHead></TableRow></TableHeader>
                <TableBody>
                  {(o?.jobs ?? []).map((j) => (
                    <TableRow key={`${j.kind}-${j.status}`}><TableCell>{j.kind}</TableCell><TableCell>{j.status}</TableCell><TableCell className="text-right tabular-nums">{j.count}</TableCell></TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card className="md:col-span-2">
            <CardHeader><CardTitle className="text-base">Dead jobs</CardTitle><CardDescription>Failed after all retries.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {(o?.dead ?? []).map((d) => (
                <div key={d.id} className="flex items-start gap-3 rounded-lg border p-3 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">#{d.id} {d.kind} · {JSON.stringify(d.payload)}</div>
                    <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-xs text-muted-foreground">{d.last_error?.slice(-800)}</pre>
                    <div className="text-xs text-muted-foreground">{formatDateTime(d.updated_at)} · {d.attempts} attempts</div>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => retry.mutate(d.id)}><RotateCcwIcon />Retry</Button>
                </div>
              ))}
              {o?.dead.length === 0 && <p className="text-sm text-muted-foreground">No dead jobs.</p>}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="costs" className="grid gap-4 pt-3 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="text-base">LLM spend, last 7 days</CardTitle><CardDescription>${totalCost.toFixed(4)} total</CardDescription></CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Day</TableHead><TableHead>Purpose</TableHead><TableHead className="text-right">Calls</TableHead><TableHead className="text-right">USD</TableHead></TableRow></TableHeader>
                <TableBody>
                  {(o?.llm_cost_7d ?? []).map((c, i) => (
                    <TableRow key={i}><TableCell>{String(c.day)}</TableCell><TableCell>{String(c.purpose)}</TableCell><TableCell className="text-right tabular-nums">{String(c.calls)}</TableCell><TableCell className="text-right tabular-nums">{Number(c.cost_usd).toFixed(4)}</TableCell></TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Eval runs</CardTitle><CardDescription>uv run python evals/run_evals.py</CardDescription></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {(o?.eval_runs ?? []).map((e) => (
                <div key={String(e.id)} className="rounded-lg border p-2">
                  <div className="text-xs text-muted-foreground">#{String(e.id)} · {String(e.branch)} @ {String(e.git_sha)} · {formatDateTime(String(e.created_at))}</div>
                  <pre className="mt-1 overflow-auto text-xs">{JSON.stringify(e.metrics, null, 1)}</pre>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
