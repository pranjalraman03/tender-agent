"use client";

import { RefreshCwIcon, ServerCrashIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

// Shown when a page can't load its data — usually the API or Postgres isn't running locally.
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-4 px-4 py-24 text-center">
      <ServerCrashIcon className="size-10 text-muted-foreground" />
      <h1 className="text-xl font-semibold">We couldn’t load this page</h1>
      <p className="text-sm text-muted-foreground">
        The tender service didn’t respond. If you’re running locally, check that Postgres and the API are up
        (<code className="rounded bg-muted px-1">./scripts/dev.sh</code> starts everything).
      </p>
      {error.digest && <p className="text-xs text-muted-foreground">Reference: {error.digest}</p>}
      <Button onClick={reset}><RefreshCwIcon />Try again</Button>
    </div>
  );
}
