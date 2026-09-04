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
        <header className="sticky top-0 z-20 border-b border-line bg-bg/90 backdrop-blur">
          <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-5 px-5">
            <Link href="/cluster" className="flex items-baseline gap-2">
              <span className="text-[13px] font-semibold tracking-tight">Kestrel</span>
              <span className="label">console</span>
            </Link>
            <nav className="flex items-center">
              <NavLink href="/cluster">Cluster</NavLink>
              <NavLink href="/tenants">Tenants</NavLink>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>
      </body>
    </html>
  );
}
