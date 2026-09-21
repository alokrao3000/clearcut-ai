import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import { Clapperboard } from "lucide-react";

import "./globals.css";
import { DisclaimerGate } from "@/components/disclaimer-gate";
import { Providers } from "@/components/providers";
import { USER_ID } from "@/lib/api";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ClearCut AI",
  description: "Pre-production asset sourcing and clearance workflow for film and media.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-background text-foreground">
        <Providers>
          <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
            <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-3 px-4 sm:px-6">
              <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
                <Clapperboard className="size-5" />
                ClearCut AI
              </Link>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                Advisory drafts only — not legal clearance
              </span>
              <span className="ml-auto rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                {USER_ID}
              </span>
            </div>
          </header>

          <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-6">
            {children}
          </main>

          <DisclaimerGate />
        </Providers>
      </body>
    </html>
  );
}
