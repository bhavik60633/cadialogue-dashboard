"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const NAV_LINKS = [
  { href: "/dashboard/queue", label: "Today's Queue" },
  { href: "/dashboard", label: "Run History", exact: true },
  { href: "/dashboard/topics", label: "Topic Library" },
  { href: "/dashboard/posts", label: "Posts" },
  { href: "/dashboard/seo", label: "SEO" },
]

export function DashboardNav() {
  const pathname = usePathname()

  return (
    <nav className="hidden sm:flex items-center gap-0.5" aria-label="Main navigation">
      {NAV_LINKS.map(({ href, label, exact }) => {
        const active = exact ? pathname === href : pathname.startsWith(href)
        return (
          <Link
            key={href}
            href={href}
            className={`
              relative px-3 py-1.5 rounded-md text-sm transition-all duration-150
              ${active
                ? "text-neutral-100 font-medium bg-neutral-800/60"
                : "text-neutral-500 hover:text-neutral-300 hover:bg-neutral-900/60"}
            `}
          >
            {label}
            {active && (
              <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-px bg-red-500/60 rounded-full" />
            )}
          </Link>
        )
      })}
    </nav>
  )
}
