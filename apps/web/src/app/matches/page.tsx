import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { TargetIcon } from "lucide-react";
import { MatchesList } from "@/components/matches/matches-list";
import { PageHeader } from "@/components/page-header";
import { serverApi } from "@/lib/server-api";
import type { Me, Meta } from "@/lib/types";

export const metadata = { title: "My matches" };

export default async function MatchesPage() {
  if (!(await auth())?.user) redirect("/login?next=/matches");
  const [meta, me] = await Promise.all([serverApi<Meta>("/meta"), serverApi<Me>("/me")]);
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-10">
      <PageHeader icon={TargetIcon} title="My matches"
                  description={<>Live tenders shortlisted for <span className="font-medium text-foreground">{me.org.name}</span>, best fit first.</>} />
      <MatchesList meta={meta} hasProfile={me.has_confirmed_profile} />
    </div>
  );
}
