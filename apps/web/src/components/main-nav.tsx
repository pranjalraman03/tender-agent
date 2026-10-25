"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export function MainNav({ items }: { items: { href: string; label: string }[] }) {
  const pathname = usePathname();
  return (
    <nav className="flex items-center gap-1 text-sm">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" || pathname.startsWith("/tenders")
          : pathname.startsWith(item.href);
        return (
          <Link key={item.href} href={item.href}
                className={cn(
                  "rounded-md px-3 py-1.5 font-medium transition-colors",
                  active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
