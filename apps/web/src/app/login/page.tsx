import { MailIcon } from "lucide-react";
import { redirect } from "next/navigation";
import { auth, devLoginEnabled, providerIds, signIn } from "@/auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

export const metadata = { title: "Sign in" };

function safeNext(value: unknown): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : "/matches";
}

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const sp = await searchParams;
  const next = safeNext(sp.next);
  if ((await auth())?.user) redirect(next);
  const hasEmail = providerIds.includes("resend");
  const hasGoogle = providerIds.includes("google");

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Sign in to Tender Agent</CardTitle>
          <CardDescription>Get tenders matched to your company and eligibility reports.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {sp.sent && (
            <Alert><MailIcon /><AlertDescription>Check your inbox for a sign-in link.</AlertDescription></Alert>
          )}
          {sp.error && (
            <Alert variant="destructive"><AlertDescription>Sign-in failed. Please try again.</AlertDescription></Alert>
          )}
          {hasEmail && (
            <form className="space-y-2" action={async (form: FormData) => {
              "use server";
              await signIn("resend", { email: String(form.get("email")), redirectTo: next });
            }}>
              <Label htmlFor="email">Work email</Label>
              <Input id="email" name="email" type="email" required placeholder="you@company.in" />
              <Button type="submit" className="w-full">Email me a sign-in link</Button>
            </form>
          )}
          {hasGoogle && (
            <form action={async () => {
              "use server";
              await signIn("google", { redirectTo: next });
            }}>
              <Button type="submit" variant="outline" className="w-full">Continue with Google</Button>
            </form>
          )}
          {devLoginEnabled && (
            <>
              {(hasEmail || hasGoogle) && <Separator />}
              <form className="space-y-2" action={async (form: FormData) => {
                "use server";
                await signIn("dev", { email: String(form.get("email")), redirectTo: next });
              }}>
                <Label htmlFor="dev-email">Development login (local only)</Label>
                <Input id="dev-email" name="email" type="email" required placeholder="owner@example.com" />
                <Button type="submit" variant="secondary" className="w-full">Sign in without a password</Button>
                <p className="text-xs text-muted-foreground">
                  Enabled by AUTH_DEV_LOGIN for local testing. Never enabled in production builds.
                </p>
              </form>
            </>
          )}
          {!hasEmail && !hasGoogle && !devLoginEnabled && (
            <p className="text-sm text-muted-foreground">
              No sign-in method is configured. Set AUTH_RESEND_KEY or AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
