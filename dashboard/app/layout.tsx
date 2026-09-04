import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import "./globals.css";
import { NavLink } from "@/components/nav-link";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Kestrel",
  description: "Operator console for the Kestrel GPU compute control plane",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <div className="min-h-screen">
          <header className="border-b sticky top-0 z-20 bg-background/85 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
              <Link href="/cluster" className="flex items-baseline gap-2">
                <span className="text-base font-semibold tracking-tight">Kestrel</span>
                <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                  operator console
                </span>
              </Link>
              <nav className="flex items-center gap-1">
                <NavLink href="/cluster">Cluster</NavLink>
                <NavLink href="/tenants">Tenants</NavLink>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
