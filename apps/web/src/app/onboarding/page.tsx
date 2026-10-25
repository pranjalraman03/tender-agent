import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { RocketIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ProfileEditor } from "@/components/profile/profile-editor";
import { serverApi } from "@/lib/server-api";
import type { Me, Meta } from "@/lib/types";

export const metadata = { title: "Set up your company" };

export default async function OnboardingPage() {
  if (!(await auth())?.user) redirect("/login?next=/onboarding");
  const [meta, me] = await Promise.all([serverApi<Meta>("/meta"), serverApi<Me>("/me")]);
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-10">
      <PageHeader icon={RocketIcon} title="Set up your company"
                  description="Two minutes now; then we match you to live tenders and check eligibility clause by clause." />
      <ProfileEditor meta={meta} me={me} onboarding />
    </div>
  );
}
