import { Suspense } from "react";
import { redirect } from "next/navigation";
import { AlertTriangle } from "lucide-react";

import { getCurrentUser, BackendUnavailableError } from "@/lib/api/auth-client";
import { LoginForm } from "@/components/auth/login-form";
import { NEXT_PARAM, resolveRedirectTarget } from "@/lib/auth/redirect";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Server Component wrapper: if a valid session already exists (e.g. the
 * user navigates back to `/login` manually, possibly carrying a `?next=`
 * from a mid-session-expiry redirect — see `(app)/layout.tsx`), skip
 * straight to that destination rather than showing the form again. The
 * actual form is a Client Component (`LoginForm`) since it needs to POST
 * and read `useSearchParams()` for the post-login redirect target.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const resolvedSearchParams = await searchParams;
  const rawNext = resolvedSearchParams[NEXT_PARAM];
  const next = Array.isArray(rawNext) ? rawNext[0] : rawNext;

  let user;
  try {
    user = await getCurrentUser();
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
          <Alert variant="destructive" className="max-w-md">
            <AlertTriangle />
            <AlertTitle>Service temporarily unavailable</AlertTitle>
            <AlertDescription>
              TraceX couldn&apos;t reach the authentication service. Please try again in a
              moment.
            </AlertDescription>
          </Alert>
        </div>
      );
    }
    throw err;
  }

  if (user) {
    redirect(resolveRedirectTarget(next));
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
