"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "cn";

/** Active state carried by an underline on the header rule, not a filled pill:
 *  one fewer shape competing with the data below. */
export function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative px-3 py-[14px] text-[13px] transition-colors",
        active ? "text-fg" : "text-fg-dim hover:text-fg",
      )}
    >
      {children}
      {active && <span aria-hidden className="absolute inset-x-2 -bottom-px h-px bg-accent" />}
    </Link>
  );
}
