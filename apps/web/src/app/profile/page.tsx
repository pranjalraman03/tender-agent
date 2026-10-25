import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { Building2Icon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ProfileEditor } from "@/components/profile/profile-editor";
import { serverApi } from "@/lib/server-api";
import type { Me, Meta } from "@/lib/types";

export const metadata = { title: "Company profile" };

export default async function ProfilePage() {
  if (!(await auth())?.user) redirect("/login?next=/profile");
  const [meta, me] = await Promise.all([serverApi<Meta>("/meta"), serverApi<Me>("/me")]);
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-10">
      <PageHeader icon={Building2Icon} title="Company profile"
                  description="Matching and eligibility checks use your confirmed profile." />
      <ProfileEditor meta={meta} me={me} />
    </div>
  );
}
