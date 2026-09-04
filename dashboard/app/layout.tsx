import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import Link from "next/link";

import "./globals.css";
import { NavLink } from "@/components/nav-link";

// Instrument Sans carries the personality: tight spacing, slightly wide
// letterforms, and enough character to not read as a framework default.
// JetBrains Mono does the work: it has the clearest 0/O and 1/l separation of
// any free mono, which matters when every node name and GPU count on this page
// is set in it.
const sans = Instrument_Sans({
  variable: "--font-sans-face",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});
const mono = JetBrains_Mono({
  variable: "--font-mono-face",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

export const metadata: Metadata = {
  title: "Kestrel",
  description: "Operator console for the Kestrel GPU compute control plane",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${sans.variable} ${mono.variable} antialiased`}>
        <header className="sticky top-0 z-20 border-b border-line bg-bg/90 backdrop-blur">
          <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-5 px-5">
            <Link href="/cluster" className="flex items-baseline gap-2">
              <span className="text-[14px] font-semibold tracking-[-0.02em]">Kestrel</span>
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
