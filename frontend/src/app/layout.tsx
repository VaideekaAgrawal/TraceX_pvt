import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { getCurrentUser } from "@/lib/api/auth-client";
import { AuthProvider } from "@/lib/auth/auth-provider";

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
  const user = await getCurrentUser();

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
