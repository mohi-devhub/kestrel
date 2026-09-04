import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";

import "./globals.css";
import { Sidebar } from "@/components/sidebar";

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
      <body className={`${sans.variable} ${mono.variable}`}>
        {/* Sidebar rather than a top bar: it anchors the left edge, gives the
            content a bounded column instead of letting it float across a wide
            viewport, and is where anyone who uses a console expects nav to be. */}
        <div className="flex min-h-[100dvh]">
          <Sidebar />
          <div className="min-w-0 flex-1">
            <div className="mx-auto max-w-[1240px] px-6 py-6 lg:px-8 lg:py-8">{children}</div>
          </div>
        </div>
      </body>
    </html>
  );
}
