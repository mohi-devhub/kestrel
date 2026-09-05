import type { Metadata } from "next";
import { Bricolage_Grotesque, Inter_Tight, JetBrains_Mono } from "next/font/google";

import "./globals.css";
import { NavBar } from "@/components/navbar";

// Display face carries the personality: Bricolage is a contemporary grotesque
// with real character in its bold weights, which is what the big readings need.
const display = Bricolage_Grotesque({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["600", "700", "800"],
});
// UI face stays quiet so it can sit under the display face without competing.
const ui = Inter_Tight({
  variable: "--font-ui",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});
// Mono is reserved for identifiers only: node names, workload names, policies.
const mono = JetBrains_Mono({
  variable: "--font-mono-face",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Kestrel",
  description: "Operator console for the Kestrel GPU compute control plane",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${ui.variable} ${mono.variable}`}>
        <NavBar />
        <main className="mx-auto max-w-[1180px] px-6 pt-28">{children}</main>
        {/* The environment note used to pad out the nav bar. It belongs here:
            still informative, no longer holding a gap open. */}
        <footer className="mx-auto max-w-[1180px] px-6 pb-12 pt-10 text-center">
          <span className="inline-flex items-center gap-2 text-[12px] text-ink-3">
            <span className="size-1.5 rounded-full bg-ok" />
            kind + KWOK, simulated GPUs. Scheduling, metering and autoscaling are real.
          </span>
        </footer>
      </body>
    </html>
  );
}
