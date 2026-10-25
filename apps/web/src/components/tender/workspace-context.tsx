"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { api } from "@/lib/api";
import type { ClauseOut } from "@/lib/types";

type Workspace = {
  tenderId: number;
  openClause: (clause: ClauseOut) => void;
};

export const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside TenderWorkspace");
  return ctx;
}

export function useClauses(tenderId: number, ids: number[]) {
  const sorted = [...new Set(ids)].sort((a, b) => a - b);
  return useQuery({
    queryKey: ["clauses", tenderId, sorted],
    enabled: sorted.length > 0,
    staleTime: Infinity,
    queryFn: () =>
      api<ClauseOut[]>(`/tenders/${tenderId}/clauses?${sorted.map((i) => `ids=${i}`).join("&")}`),
  });
}
