"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"

const NAV_LINKS = [
  { href: "/dashboard/queue",  label: "Today's Queue" },
  { href: "/dashboard/review", label: "Review" },                 // ← new: drafts pending approval
  { href: "/dashboard",        label: "Run History", exact: true },
  { href: "/dashboard/topics", label: "Topic Library" },
  { href: "/dashboard/posts",  label: "Posts" },
  { href: "/dashboard/seo",    label: "SEO" },
]

export function DashboardNav() {
  const pathname = usePathname()
  const [reviewCount, setReviewCount] = useState<number | null>(null)

  // Poll the pending-review queue every 20s for the badge counter
  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const res = await fetch("/api/py/runs/pending-review", { cache: "no-store" })
        if (!res.ok) return
        const data = await res.json()
        if (alive) setReviewCount(typeof data?.count === "number" ? data.count : null)
      } catch { /* network blip — ignore */ }
    }
    poll()
    const id = setInterval(poll, 20_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  return (
    <nav className="hidden sm:flex items-center gap-0.5" aria-label="Main navigation">
      {NAV_LINKS.map(({ href, label, exact }) => {
        const active = exact ? pathname === href : pathname.startsWith(href)
        const isReview = href === "/dashboard/review"
        return (
          <Link
            key={href}
            href={href}
            className={`
              relative px-3 py-1.5 rounded-md text-sm transition-all duration-150 inline-flex items-center gap-1.5
              ${active
                ? "text-neutral-100 font-medium bg-neutral-800/60"
                : "text-neutral-500 hover:text-neutral-300 hover:bg-neutral-900/60"}
            `}
          >
            {label}
            {isReview && reviewCount !== null && reviewCount > 0 && (
              <span
                aria-label={`${reviewCount} drafts awaiting review`}
                className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold border border-amber-500/40">
                {reviewCount}
              </span>
            )}
            {active && (
              <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-px bg-red-500/60 rounded-full" />
            )}
          </Link>
        )
      })}
    </nav>
  )
}
