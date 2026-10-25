/** "₹1.50 Cr", "₹27.69 L", "₹55,382" - the way Indian tender values are usually read. */
export function formatInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    ...IST, day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  }) + " IST";
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { ...IST, day: "2-digit", month: "short", year: "numeric" });
}

/** "Closes in 3 days" / "Closes today" */
export function closesIn(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "No deadline";
  const days = Math.floor((new Date(iso).getTime() - now.getTime()) / 86_400_000);
  if (days < 0) return "Closed";
  if (days === 0) return "Closes today";
  if (days === 1) return "Closes tomorrow";
  return `Closes in ${days} days`;
}

export function industryName(slug: string, industries: { slug: string; name: string }[]): string {
  return industries.find((i) => i.slug === slug)?.name ?? slug.replace(/_/g, " ");
}

export const FIT_LABEL: Record<string, string> = {
  good: "Good fit",
  possible: "Possible fit",
  not_eligible: "Not eligible",
};

export const VERDICT_LABEL: Record<string, string> = {
  eligible: "Eligible",
  possibly_eligible: "Possibly eligible",
  not_eligible: "Not eligible",
  needs_review: "Needs review",
};

export const STATUS_LABEL: Record<string, string> = {
  met: "Met",
  not_met: "Not met",
  unclear: "Unclear",
  exempt: "Exempt",
};

/** Deadline within three days (used to highlight urgent tenders). */
export function isClosingSoon(iso: string | null | undefined, now: Date = new Date()): boolean {
  if (!iso) return false;
  const ms = new Date(iso).getTime() - now.getTime();
  return ms >= 0 && ms < 3 * 86_400_000;
}
