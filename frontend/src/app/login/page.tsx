import { Suspense } from "react";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/api/auth-client";
import { LoginForm } from "@/components/auth/login-form";

/**
 * Server Component wrapper: if a valid session already exists (e.g. the
 * user navigates back to `/login` manually), skip straight to the
 * workspace rather than showing the form again. The actual form is a
 * Client Component (`LoginForm`) since it needs to POST and read
 * `useSearchParams()` for the post-login redirect target.
 */
export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/dashboard");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
