import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { MatchesList } from "@/components/matches/matches-list";
import { serverApi } from "@/lib/server-api";
import type { Me, Meta } from "@/lib/types";

export const metadata = { title: "My matches" };

export default async function MatchesPage() {
  if (!(await auth())?.user) redirect("/login?next=/matches");
  const [meta, me] = await Promise.all([serverApi<Meta>("/meta"), serverApi<Me>("/me")]);
  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold">My matches</h1>
        <p className="text-muted-foreground">Live tenders shortlisted for {me.org.name}, best fit first.</p>
      </div>
      <MatchesList meta={meta} hasProfile={me.has_confirmed_profile} />
    </div>
  );
}
