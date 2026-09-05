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
 * Floating navigation, sized to its contents.
 *
 * The bar used to span the full width with two destinations in it and a status
 * chip pinned to the far edge, which left a large dead gap in the middle and
 * made the chrome look unfinished. Hugging the content removes that gap by
 * construction, and still works if a third destination ever appears.
 *
 * The two destinations are drawn as a segmented control, matching the
 * job/endpoint switch in the submit form, so the same shape means the same thing
 * in both places.
 */
export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="fixed inset-x-0 top-0 z-30 flex justify-center px-6 pt-5">
      <nav className="flex items-center gap-2 rounded-full border border-line bg-card/85 py-1.5 pl-2.5 pr-1.5 shadow-float backdrop-blur-xl">
        <Link href="/cluster" className="flex shrink-0 items-center gap-2">
          <Mark />
          <span className="font-display text-[15px] font-bold tracking-tight text-ink">
            Kestrel
          </span>
        </Link>

        <span aria-hidden className="mx-0.5 h-5 w-px bg-line" />

        <div className="flex items-center gap-1 rounded-full bg-sunk p-1">
          {NAV.map(({ href, label, Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-card text-ink shadow-card"
                    : "text-ink-3 hover:text-ink",
                )}
              >
                <Icon size={13.5} strokeWidth={2} />
                {label}
              </Link>
            );
          })}
        </div>
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
