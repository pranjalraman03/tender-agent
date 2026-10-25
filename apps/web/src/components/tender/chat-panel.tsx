"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2Icon, SendIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Citation } from "@/components/tender/citation";
import { useClauses } from "@/components/tender/workspace-context";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, readSSE } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

const SUGGESTIONS = ["What is the EMD and is it waived for MSEs?", "What experience is required?", "What is the bid deadline?"];
const CITATION = /\[C:(\d+)\]/g;

const fallbackSessions = new Map<number, string>();

/** One chat session per tender per browser; stable across renders and reloads. */
function sessionFor(tenderId: number): string {
  const key = `chat-session-${tenderId}`;
  try {
    const existing = localStorage.getItem(key);
    if (existing) return existing;
    const fresh = crypto.randomUUID();
    localStorage.setItem(key, fresh);
    return fresh;
  } catch {
    if (!fallbackSessions.has(tenderId)) fallbackSessions.set(tenderId, crypto.randomUUID());
    return fallbackSessions.get(tenderId)!;
  }
}

const noopSubscribe = () => () => {};

type Turn = { role: "user" | "assistant"; content: string; cited: number[] };

export function ChatPanel({ tenderId, llmConfigured }: { tenderId: number; llmConfigured: boolean }) {
  const qc = useQueryClient();
  const sessionId = useSyncExternalStore(noopSubscribe, () => sessionFor(tenderId), () => null);
  // Turns sent in this page view; saved history comes from the query below.
  const [pending, setPending] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const history = useQuery({
    queryKey: ["chat", tenderId, sessionId],
    enabled: !!sessionId,
    queryFn: () => api<ChatMessage[]>(`/tenders/${tenderId}/chat/${sessionId}`),
  });
  const turns: Turn[] = useMemo(() => [
    ...(history.data ?? []).map((m) => ({ role: m.role, content: m.content, cited: m.cited_clause_ids })),
    ...pending,
  ], [history.data, pending]);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [turns]);

  const citedIds = useMemo(() => turns.flatMap((t) => t.cited), [turns]);
  const clauses = useClauses(tenderId, citedIds);
  const clauseById = new Map((clauses.data ?? []).map((c) => [c.id, c]));

  async function ask(text: string) {
    if (!sessionId || !text.trim() || streaming) return;
    setQuestion("");
    setStreaming(true);
    setPending([{ role: "user", content: text, cited: [] }, { role: "assistant", content: "", cited: [] }]);
    try {
      const response = await fetch(`/api/backend/tenders/${tenderId}/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, question: text }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail ?? `Chat failed (${response.status})`);
      }
      for await (const { event, data } of readSSE(response)) {
        const payload = JSON.parse(data);
        setPending((t) => {
          const copy = [...t];
          const last = copy[copy.length - 1];
          if (event === "token") copy[copy.length - 1] = { ...last, content: last.content + payload.text };
          if (event === "done") copy[copy.length - 1] = { ...last, content: payload.text, cited: payload.cited };
          if (event === "error") copy[copy.length - 1] = { ...last, content: payload.message };
          return copy;
        });
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Chat failed");
      setPending([]);
      setQuestion(text);
      setStreaming(false);
      return;
    }
    // The turn is saved server-side; show it from history from now on.
    await qc.invalidateQueries({ queryKey: ["chat", tenderId, sessionId] });
    setPending([]);
    setStreaming(false);
  }

  function render(content: string): ReactNode[] {
    const parts: ReactNode[] = [];
    let last = 0;
    for (const m of content.matchAll(CITATION)) {
      parts.push(content.slice(last, m.index));
      const clause = clauseById.get(Number(m[1]));
      parts.push(clause ? <Citation key={`${m.index}`} clause={clause} /> : null);
      last = (m.index ?? 0) + m[0].length;
    }
    parts.push(content.slice(last));
    return parts;
  }

  if (!llmConfigured) {
    return <p className="p-6 text-sm text-muted-foreground">Chat needs an LLM API key, which isn’t configured yet.</p>;
  }
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {turns.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Ask anything about this tender. Answers cite the clauses they come from.</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => <Button key={s} variant="outline" size="sm" onClick={() => ask(s)}>{s}</Button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "flex justify-end" : ""}>
            <div className={t.role === "user"
              ? "max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground"
              : "max-w-full whitespace-pre-wrap text-sm leading-relaxed"}>
              {t.role === "assistant" ? (t.content ? render(t.content) : <Loader2Icon className="size-4 animate-spin text-muted-foreground" />) : t.content}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <form className="flex items-end gap-2 border-t p-3" onSubmit={(e) => { e.preventDefault(); void ask(question); }}>
        <Textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} maxLength={1000}
                  placeholder="e.g. Is there a turnover requirement?" className="min-h-0 resize-none"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(question); } }} />
        <Button type="submit" size="icon" disabled={streaming || !question.trim()} aria-label="Send">
          {streaming ? <Loader2Icon className="animate-spin" /> : <SendIcon />}
        </Button>
      </form>
    </div>
  );
}
