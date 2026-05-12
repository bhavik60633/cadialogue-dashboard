"use client"

import { useEffect, useState } from "react"

interface UsageStats {
  month: string
  article_count: number
  image_count: number
  batch_count: number
  estimated_usd: number
  estimated_inr: number
  monthly_cap_usd: number
  monthly_cap_inr: number
  pct_used: number
  is_active: boolean
}

export function UsageIndicator() {
  const [stats, setStats] = useState<UsageStats | null>(null)
  const [open, setOpen] = useState(false)

  const fetchStats = async () => {
    try {
      const res = await fetch("/api/py/usage/stats")
      if (res.ok) setStats(await res.json())
    } catch { /* silent — indicator is non-critical */ }
  }

  // Poll every 12 s when active, every 60 s when idle
  useEffect(() => {
    fetchStats()
    const interval = setInterval(fetchStats, stats?.is_active ? 12_000 : 60_000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stats?.is_active])

  if (!stats) return null

  const pct    = Math.min(stats.pct_used, 100)
  const active = stats.is_active

  // Dot colour: amber-pulse when running, green when idle
  const dotClass = active
    ? "bg-amber-400 animate-pulse"
    : "bg-emerald-500"

  // Bar colour gradient based on spend %
  const barColor =
    pct >= 80 ? "bg-red-500"
    : pct >= 50 ? "bg-amber-400"
    : "bg-emerald-500"

  return (
    <div className="relative">
      {/* ── Pill trigger ── */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-lg border border-neutral-800/60 bg-neutral-900/40 hover:bg-neutral-900/80 hover:border-neutral-700 transition-all cursor-pointer"
        title="OpenAI usage this month"
      >
        {/* Status dot */}
        <span className={`h-2 w-2 rounded-full shrink-0 ${dotClass}`} />

        {/* Spend */}
        <span className="text-[11px] font-medium text-neutral-400 tabular-nums">
          ₹{stats.estimated_inr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
        </span>

        {/* Mini progress bar */}
        <span className="w-14 h-1 rounded-full bg-neutral-800 overflow-hidden">
          <span
            className={`block h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </span>

        {/* % */}
        <span className="text-[10px] text-neutral-600 tabular-nums">{pct.toFixed(0)}%</span>
      </button>

      {/* ── Dropdown panel ── */}
      {open && (
        <>
          {/* backdrop */}
          <div
            className="fixed inset-0 z-30"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-9 z-40 w-72 rounded-xl border border-neutral-700 bg-[#111113] shadow-2xl p-4 space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between">
              <p className="text-[13px] font-semibold text-neutral-200">
                OpenAI Usage
                <span className="ml-2 text-[10px] text-neutral-600 font-normal">
                  {stats.month}
                </span>
              </p>
              <span className={`flex items-center gap-1.5 text-[11px] font-medium ${active ? "text-amber-400" : "text-emerald-400"}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
                {active ? "Running…" : "Idle"}
              </span>
            </div>

            {/* Spend bar */}
            <div>
              <div className="flex justify-between text-[11px] mb-1.5">
                <span className="text-neutral-400">
                  ₹{stats.estimated_inr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  <span className="text-neutral-700 ml-1">(${stats.estimated_usd})</span>
                </span>
                <span className="text-neutral-600">
                  cap ₹{stats.monthly_cap_inr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="mt-1 text-right text-[10px] text-neutral-700">
                {pct.toFixed(1)}% of monthly cap used
              </p>
            </div>

            {/* Breakdown */}
            <div className="space-y-2 border-t border-neutral-800 pt-3">
              <p className="text-[10px] text-neutral-600 uppercase tracking-wider font-semibold mb-2">
                This month&apos;s breakdown
              </p>
              <Row label="Articles generated" value={stats.article_count} unit="× ≈$0.09" />
              <Row label="Topic discoveries"  value={stats.batch_count}   unit="× ≈$0.002" />
              <Row label="AI images created"  value={stats.image_count}   unit="× ≈$0.06" />
            </div>

            {/* Which tasks use the key */}
            <div className="border-t border-neutral-800 pt-3 space-y-1.5">
              <p className="text-[10px] text-neutral-600 uppercase tracking-wider font-semibold mb-2">
                Uses OpenAI key
              </p>
              {[
                "✅ Topic scoring & ranking (gpt-4o-mini)",
                "✅ Article writing (gpt-4o)",
                "✅ Article humanising (gpt-4o)",
                "✅ SEO meta generation (gpt-4o-mini)",
                "✅ Image idea suggestions (gpt-4o-mini)",
                "✅ AI image generation (gpt-image-1)",
              ].map((t) => (
                <p key={t} className="text-[11px] text-neutral-400">{t}</p>
              ))}
              <p className="text-[10px] text-neutral-600 uppercase tracking-wider font-semibold mt-3 mb-2">
                Does NOT use OpenAI key
              </p>
              {[
                "🚫 Market data fetch (Yahoo / APIs)",
                "🚫 News topic discovery (NewsAPI)",
                "🚫 Pexels photo search (free API)",
                "🚫 WordPress publishing (WP REST)",
                "🚫 SEO indexing (Google / IndexNow)",
              ].map((t) => (
                <p key={t} className="text-[11px] text-neutral-500">{t}</p>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Row({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div className="flex items-center justify-between text-[12px]">
      <span className="text-neutral-500">{label}</span>
      <span className="text-neutral-300 tabular-nums font-medium">
        {value}
        <span className="text-neutral-700 font-normal ml-1">{unit}</span>
      </span>
    </div>
  )
}
