import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { getCurrentUser, BackendUnavailableError } from "@/lib/api/auth-client";
import { AuthProvider } from "@/lib/auth/auth-provider";
import type { CurrentUser } from "@/lib/api/types";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TraceX",
  description: "AML investigation workspace",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Server-side resolution of "who is logged in": reads the session
  // cookie (if any) and calls the real `GET /auth/me`. A missing/expired
  // token resolves to `null` here — pages under the guarded route group
  // handle the "not logged in" redirect themselves (see
  // `app/(app)/layout.tsx`); this root layout's only job is to seed the
  // client-side `AuthProvider` once, so nothing downstream re-fetches it.
  //
  // This is imported by every route, including `/login` — a backend
  // outage must not crash the whole app. `getCurrentUser()` throws
  // `BackendUnavailableError` (as opposed to returning `null`) precisely
  // to distinguish "backend is down" from "not logged in"; here we fall
  // back to rendering as logged-out rather than crashing. Page-level
  // layouts that make their own `getCurrentUser()` call (`(app)/layout.tsx`,
  // `login/page.tsx`) are responsible for rendering the actual "service
  // unavailable" UI — this root layout just needs to not blow up.
  let user: CurrentUser | null;
  try {
    user = await getCurrentUser();
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      user = null;
    } else {
      throw err;
    }
  }

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AuthProvider user={user}>{children}</AuthProvider>
      </body>
    </html>
  );
}
