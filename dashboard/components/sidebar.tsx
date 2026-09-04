"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "cn";

const NAV = [
  { href: "/cluster", label: "Cluster" },
  { href: "/tenants", label: "Tenants" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-[100dvh] w-[228px] shrink-0 flex-col border-r border-hair bg-s1 md:flex">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <Mark />
        <div className="min-w-0">
          <div className="t-title text-[14px] leading-none">Kestrel</div>
          <div className="mt-1 text-[10.5px] leading-none text-ink-4">operator console</div>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 px-3">
        {NAV.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "rounded-sm px-2.5 py-1.5 text-[13px] transition-colors",
                active
                  ? "bg-s3 font-medium text-ink"
                  : "text-ink-3 hover:bg-s2 hover:text-ink",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto border-t border-hair px-5 py-4">
        <div className="t-label mb-2">Simulated fleet</div>
        <p className="text-[11.5px] leading-snug text-ink-4">
          kind + KWOK nodes advertising fake GPU capacity. The scheduling, metering and
          autoscaling above them are real.
        </p>
      </div>
    </aside>
  );
}

/** A 4x4 block, which is what this cluster physically is: 4 nodes of 4 GPUs. */
function Mark() {
  return (
    <span
      aria-hidden
      className="grid shrink-0 grid-cols-2 gap-[2px] rounded-sm border border-accent-line bg-accent-weak p-[3px]"
    >
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={cn("size-[4px] rounded-[1px]", i < 3 ? "bg-accent" : "bg-accent/25")}
        />
      ))}
    </span>
  );
}
