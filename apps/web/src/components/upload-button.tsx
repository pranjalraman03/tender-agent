"use client";

import { Loader2Icon, UploadIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { UploadResult } from "@/lib/types";

/** Upload a tender PDF or ZIP to the given API path (user corrigendum or admin queue). */
export function UploadButton({ path, label = "Upload PDF / ZIP", onDone, variant = "outline", size = "sm" }: {
  path: string;
  label?: string;
  onDone?: (r: UploadResult) => void;
  variant?: "outline" | "default" | "secondary";
  size?: "sm" | "default";
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function upload(file: File) {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<UploadResult>(path, { method: "POST", body: form });
      if (result.new_documents) toast.success(`${result.new_documents} document(s) added — parsing now.`);
      else toast.info("Already uploaded; nothing new.");
      if (result.skipped_files.length) toast.info(`Skipped non-PDF files: ${result.skipped_files.join(", ")}`);
      onDone?.(result);
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      <input ref={input} type="file" accept=".pdf,.zip,application/pdf,application/zip" hidden
             onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
      <Button variant={variant} size={size} disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}{label}
      </Button>
    </>
  );
}
