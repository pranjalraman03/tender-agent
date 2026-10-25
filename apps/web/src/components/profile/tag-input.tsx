"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

export function TagInput({ value, onChange, placeholder }: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const items = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (items.length) onChange([...value, ...items.filter((i) => !value.includes(i))]);
    setDraft("");
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {value.map((v) => (
          <Badge key={v} variant="secondary" className="gap-1 pr-1">
            {v}
            <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}>
              <XIcon className="size-3" />
            </button>
          </Badge>
        ))}
      </div>
      <Input value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)} onBlur={add}
             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
    </div>
  );
}
