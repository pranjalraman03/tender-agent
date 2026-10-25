"use client";

import { ChevronLeftIcon, ChevronRightIcon, ZoomInIcon, ZoomOutIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

// Must be set in the module that renders <Document> (see react-pdf README). The worker file
// is copied into /public on install by scripts/copy-pdf-worker.mjs.
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export default function PdfViewer({ url, page, onPageChange }: {
  url: string;
  page: number;
  onPageChange: (page: number) => void;
}) {
  const [pages, setPages] = useState(0);
  const [scale, setScale] = useState(1.1);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.min(entry.contentRect.width - 16, 900)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const go = (p: number) => onPageChange(Math.min(Math.max(1, p), pages || 1));

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b px-2 py-1.5 text-sm">
        <Button variant="ghost" size="icon-sm" onClick={() => go(page - 1)} disabled={page <= 1} aria-label="Previous page">
          <ChevronLeftIcon />
        </Button>
        <span className="tabular-nums">Page {page} / {pages || "…"}</span>
        <Button variant="ghost" size="icon-sm" onClick={() => go(page + 1)} disabled={page >= pages} aria-label="Next page">
          <ChevronRightIcon />
        </Button>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" onClick={() => setScale((s) => Math.max(0.6, s - 0.15))} aria-label="Zoom out">
            <ZoomOutIcon />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setScale((s) => Math.min(2.5, s + 0.15))} aria-label="Zoom in">
            <ZoomInIcon />
          </Button>
          <Button variant="link" size="sm" render={<a href={url} target="_blank" rel="noreferrer" />}>Open PDF</Button>
        </div>
      </div>
      <div ref={box} className="flex-1 overflow-auto bg-muted/40 p-2">
        <Document
          file={url}
          onLoadSuccess={({ numPages }) => setPages(numPages)}
          loading={<Skeleton className="mx-auto h-[70vh] w-full max-w-2xl" />}
          error={<p className="p-6 text-sm text-destructive">Could not load this PDF.</p>}
        >
          <Page pageNumber={page} width={width * scale} className="mx-auto w-fit shadow-sm" />
        </Document>
      </div>
    </div>
  );
}
