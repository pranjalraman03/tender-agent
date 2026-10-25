import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { ProfileEditor } from "@/components/profile/profile-editor";
import { serverApi } from "@/lib/server-api";
import type { Me, Meta } from "@/lib/types";

export const metadata = { title: "Company profile" };

export default async function ProfilePage() {
  if (!(await auth())?.user) redirect("/login?next=/profile");
  const [meta, me] = await Promise.all([serverApi<Meta>("/meta"), serverApi<Me>("/me")]);
  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-8">
      <h1 className="text-2xl font-semibold">Company profile</h1>
      <ProfileEditor meta={meta} me={me} />
    </div>
  );
}
