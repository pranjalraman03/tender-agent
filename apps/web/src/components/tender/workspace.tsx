"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";
import { ChatPanel } from "@/components/tender/chat-panel";
import { ReportPanel } from "@/components/tender/report-panel";
import { WorkspaceContext } from "@/components/tender/workspace-context";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ClauseOut, TenderDetail } from "@/lib/types";

// pdf.js only runs in the browser.
const PdfViewer = dynamic(() => import("@/components/tender/pdf-viewer"), {
  ssr: false,
  loading: () => <Skeleton className="m-4 h-[60vh]" />,
});

export function TenderWorkspace({ tender, signedIn, hasProfile, llmConfigured }: {
  tender: TenderDetail;
  signedIn: boolean;
  hasProfile: boolean;
  llmConfigured: boolean;
}) {
  const [tab, setTab] = useState<string>(signedIn ? "eligibility" : "documents");
  const [docId, setDocId] = useState<number | null>(tender.documents[0]?.id ?? null);
  const [page, setPage] = useState(1);

  const openClause = useCallback((clause: ClauseOut) => {
    setDocId(clause.document_id);
    setPage(clause.page_start);
    setTab("documents");
  }, []);
  const ctx = useMemo(() => ({ tenderId: tender.id, openClause }), [tender.id, openClause]);
  const fileUrl = docId ? `/api/backend/tenders/${tender.id}/documents/${docId}/file` : null;

  return (
    <WorkspaceContext value={ctx}>
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))} className="surface flex h-[calc(100vh-9rem)] flex-col overflow-hidden lg:sticky lg:top-24">
        <TabsList className="m-2">
          {signedIn && <TabsTrigger value="eligibility">My eligibility</TabsTrigger>}
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="chat">Ask this tender</TabsTrigger>
        </TabsList>
        {signedIn && (
          <TabsContent value="eligibility" className="min-h-0 flex-1 overflow-y-auto">
            <ReportPanel tenderId={tender.id} hasProfile={hasProfile} />
          </TabsContent>
        )}
        <TabsContent value="documents" className="flex min-h-0 flex-1 flex-col">
          {tender.documents.length > 1 && (
            <div className="flex gap-1 overflow-x-auto border-b px-2 pb-2">
              {tender.documents.map((d) => (
                <button key={d.id} onClick={() => { setDocId(d.id); setPage(1); }}
                        className={`shrink-0 rounded-md px-2 py-1 text-xs ${d.id === docId ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
                  {d.filename ?? `Document ${d.id}`}
                </button>
              ))}
            </div>
          )}
          <div className="min-h-0 flex-1">
            {fileUrl ? <PdfViewer key={docId} url={fileUrl} page={page} onPageChange={setPage} />
              : <p className="p-6 text-sm text-muted-foreground">No documents.</p>}
          </div>
        </TabsContent>
        <TabsContent value="chat" className="min-h-0 flex-1">
          <ChatPanel tenderId={tender.id} llmConfigured={llmConfigured} />
        </TabsContent>
      </Tabs>
    </WorkspaceContext>
  );
}
