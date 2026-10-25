import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { ProfileEditor } from "@/components/profile/profile-editor";
import { serverApi } from "@/lib/server-api";
import type { Me, Meta } from "@/lib/types";

export const metadata = { title: "Set up your company" };

export default async function OnboardingPage() {
  if (!(await auth())?.user) redirect("/login?next=/onboarding");
  const [meta, me] = await Promise.all([serverApi<Meta>("/meta"), serverApi<Me>("/me")]);
  return (
    <div className="mx-auto max-w-4xl space-y-2 px-4 py-8">
      <h1 className="text-2xl font-semibold">Set up your company</h1>
      <p className="text-muted-foreground">Two minutes now; then we match you to live tenders and check eligibility clause by clause.</p>
      <div className="pt-4"><ProfileEditor meta={meta} me={me} onboarding /></div>
    </div>
  );
}
