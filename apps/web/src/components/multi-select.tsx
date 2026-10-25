"use client";

import { ChevronDownIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type Option = { value: string; label: string };

export function MultiSelect({
  label, options, value, onChange, searchable = true,
}: {
  label: string;
  options: Option[];
  value: string[];
  onChange: (next: string[]) => void;
  searchable?: boolean;
}) {
  const [query, setQuery] = useState("");
  const shown = useMemo(
    () => options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase())),
    [options, query],
  );
  const toggle = (v: string, on: boolean) =>
    onChange(on ? [...value, v] : value.filter((x) => x !== v));
  const summary =
    value.length === 0 ? `All ${label.toLowerCase()}`
      : value.length === 1 ? options.find((o) => o.value === value[0])?.label ?? value[0]
        : `${value.length} ${label.toLowerCase()}`;
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" className="h-9 justify-between gap-2 font-normal" />}>
        <span className="text-muted-foreground">{label}:</span>
        <span className="max-w-40 truncate">{summary}</span>
        <ChevronDownIcon className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        {searchable && (
          <div className="border-b p-2">
            <Input placeholder={`Search ${label.toLowerCase()}…`} value={query}
                   onChange={(e) => setQuery(e.target.value)} className="h-8" />
          </div>
        )}
        <div className="max-h-72 overflow-y-auto p-1">
          {shown.map((o) => {
            const checked = value.includes(o.value);
            return (
              <label key={o.value}
                     className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                <Checkbox checked={checked} onCheckedChange={(on) => toggle(o.value, on)} />
                {o.label}
              </label>
            );
          })}
          {shown.length === 0 && <p className="px-2 py-3 text-sm text-muted-foreground">No matches</p>}
        </div>
        {value.length > 0 && (
          <div className="border-t p-1">
            <Button variant="ghost" size="sm" className="w-full" onClick={() => onChange([])}>Clear</Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
