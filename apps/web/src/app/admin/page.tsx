import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { ShieldIcon } from "lucide-react";
import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { PageHeader } from "@/components/page-header";
import { serverApi } from "@/lib/server-api";
import type { Me } from "@/lib/types";

export const metadata = { title: "Admin" };

export default async function AdminPage() {
  if (!(await auth())?.user) redirect("/login?next=/admin");
  const me = await serverApi<Me>("/me");
  if (me.role !== "admin") notFound();
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-10">
      <PageHeader icon={ShieldIcon} title="Admin" description="Document intake, pipeline health, LLM spend and evals." />
      <AdminDashboard />
    </div>
  );
}
