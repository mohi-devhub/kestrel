"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, Users } from "lucide-react";

import { cn } from "cn";

const NAV = [
  { href: "/cluster", label: "Cluster", Icon: Boxes },
  { href: "/tenants", label: "Tenants", Icon: Users },
];

/**
 * Floating pill navigation.
 *
 * A console this size does not have enough destinations to justify a full
 * sidebar, and a sidebar spends 230px of every viewport saying so. Floating the
 * nav gives the content the whole width and keeps the chrome to one object.
 */
export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="fixed inset-x-0 top-0 z-30 flex justify-center px-6 pt-5">
      <nav className="flex w-full max-w-[1180px] items-center gap-4 rounded-full border border-line bg-card/85 py-2 pl-3 pr-4 shadow-float backdrop-blur-xl">
        <Link href="/cluster" className="flex shrink-0 items-center gap-2.5 pl-1">
          <Mark />
          <span className="font-display text-[16px] font-bold tracking-tight text-ink">
            Kestrel
          </span>
        </Link>

        <div className="flex items-center gap-1">
          {NAV.map(({ href, label, Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13.5px] font-medium transition-colors",
                  active
                    ? "bg-ink text-card"
                    : "text-ink-3 hover:bg-sunk hover:text-ink",
                )}
              >
                <Icon size={14} strokeWidth={2} />
                {label}
              </Link>
            );
          })}
        </div>

        <span className="ml-auto hidden shrink-0 items-center gap-2 rounded-full bg-sunk px-3 py-1.5 text-[12px] text-ink-3 sm:flex">
          <span className="size-1.5 rounded-full bg-ok" />
          kind + KWOK, simulated GPUs
        </span>
      </nav>
    </header>
  );
}

/** 4x4 block: what this cluster physically is, four nodes of four GPUs. */
function Mark() {
  return (
    <span
      aria-hidden
      className="grid size-7 shrink-0 place-content-center rounded-lg bg-accent"
      style={{ boxShadow: "0 1px 2px rgba(37,99,235,.35)" }}
    >
      <span className="grid grid-cols-2 gap-[2.5px]">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn("size-[4.5px] rounded-[1.5px] bg-white", i === 3 && "opacity-40")}
          />
        ))}
      </span>
    </span>
  );
}
