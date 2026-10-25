import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { serverApi } from "@/lib/server-api";
import type { Me } from "@/lib/types";

export const metadata = { title: "Admin" };

export default async function AdminPage() {
  if (!(await auth())?.user) redirect("/login?next=/admin");
  const me = await serverApi<Me>("/me");
  if (me.role !== "admin") notFound();
  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-8">
      <h1 className="text-2xl font-semibold">Admin</h1>
      <AdminDashboard />
    </div>
  );
}
