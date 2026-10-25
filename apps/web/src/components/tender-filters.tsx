"use client";

import { SearchIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";
import { MultiSelect } from "@/components/multi-select";
import { Input } from "@/components/ui/input";

export function TenderFilters({
  states, industries, showSearch = true,
}: {
  states: string[];
  industries: { slug: string; name: string }[];
  showSearch?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [q, setQ] = useState(params.get("q") ?? "");

  function update(key: string, values: string[] | string) {
    const next = new URLSearchParams(params.toString());
    next.delete(key);
    next.delete("page");
    for (const v of Array.isArray(values) ? values : values ? [values] : []) next.append(key, v);
    startTransition(() => router.push(`${pathname}?${next.toString()}`, { scroll: false }));
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${pending ? "opacity-70" : ""}`}>
      <MultiSelect label="States" value={params.getAll("state")} onChange={(v) => update("state", v)}
                   options={states.map((s) => ({ value: s, label: s }))} />
      <MultiSelect label="Industries" value={params.getAll("industry")} onChange={(v) => update("industry", v)}
                   options={industries.map((i) => ({ value: i.slug, label: i.name }))} />
      {showSearch && (
        <form className="relative min-w-56 flex-1" onSubmit={(e) => { e.preventDefault(); update("q", q.trim()); }}>
          <SearchIcon className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, buyer or scope…"
                 className="h-9 pl-8" />
        </form>
      )}
    </div>
  );
}
