import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({ icon: Icon, title, description, actions }: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-5">
      <div className="flex items-start gap-3">
        {Icon && (
          <span className="mt-0.5 grid size-10 place-items-center rounded-xl bg-accent text-accent-foreground">
            <Icon className="size-5" />
          </span>
        )}
        <div>
          <h1 className="text-2xl font-semibold">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
      </div>
      {actions}
    </div>
  );
}
