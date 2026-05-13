"use client"

import { useEffect, useState, useCallback } from "react"

// ── Types ─────────────────────────────────────────────────────────────────────

interface EmbeddingStatus { count: number; last_updated: number }
interface LinkStats {
  total_links: number; total_pages: number; orphan_pages: number;
  avg_outgoing: number; avg_incoming: number; last_rebuilt: number
}
interface CoverageReport {
  authority_score: number; total_pillars: number; weak_pillars: number;
  total_articles: number; total_gap_articles: number; last_updated: number
}
interface FreshnessReport {
  stale_count: number; warning_count: number; last_scan: number;
  top_stale: Array<{ post_id: number; title: string; age_days: number; pct_stale: number }>
}
interface ScoringReport { articles_scored: number; average_score: number; needs_update: number }
interface RoadmapItem {
  title: string; focus_keyword: string; intent: string; priority: string; pillar: string
}
interface DashboardData {
  embeddings: EmbeddingStatus
  linking: LinkStats
  coverage: CoverageReport
  freshness: FreshnessReport
  scoring: ScoringReport
  keywords: { easy_wins: Array<{ kw: string; difficulty: number; intent: string; volume_est: number }> }
  roadmap: { top_items: RoadmapItem[] }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | undefined | null, decimals = 0): string {
  if (n == null) return "—"
  return n.toLocaleString("en-IN", { maximumFractionDigits: decimals })
}

function relTime(ts: number): string {
  if (!ts) return "Never"
  const mins = Math.floor((Date.now() / 1000 - ts) / 60)
  if (mins < 1) return "Just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function gradeColor(score: number): string {
  if (score >= 80) return "text-emerald-400"
  if (score >= 60) return "text-amber-400"
  return "text-red-400"
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({
  label, value, sub, accent = false, onClick
}: {
  label: string; value: string | number; sub?: string; accent?: boolean; onClick?: () => void
}) {
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border p-4 transition-all ${
        accent
          ? "border-red-500/30 bg-red-950/20"
          : "border-neutral-800 bg-neutral-900/50"
      } ${onClick ? "cursor-pointer hover:border-neutral-600" : ""}`}
    >
      <p className="text-[11px] text-neutral-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent ? "text-red-400" : "text-neutral-100"}`}>
        {value}
      </p>
      {sub && <p className="text-[11px] text-neutral-600 mt-1">{sub}</p>}
    </div>
  )
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-[13px] font-semibold text-neutral-200">{title}</h2>
      {subtitle && <p className="text-[11px] text-neutral-600 mt-0.5">{subtitle}</p>}
    </div>
  )
}

function ActionButton({
  label, onClick, loading, variant = "default"
}: {
  label: string; onClick: () => void; loading?: boolean; variant?: "default" | "danger" | "primary"
}) {
  const colors = {
    default: "border-neutral-700 text-neutral-400 hover:text-neutral-200 hover:border-neutral-500",
    danger:  "border-red-800/60 text-red-400 hover:text-red-300 hover:border-red-600",
    primary: "border-red-600/60 bg-red-600/10 text-red-400 hover:bg-red-600/20 hover:text-red-300",
  }
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`h-7 px-3 rounded-md text-[11px] border transition-all ${colors[variant]} disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      {loading ? "Working…" : label}
    </button>
  )
}

// ── Main dashboard ────────────────────────────────────────────────────────────

export default function SeoDashboardPage() {
  const [data, setData]       = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [jobs, setJobs]       = useState<Record<string, boolean>>({})
  const [toast, setToast]     = useState<string | null>(null)

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 4000)
  }

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/py/seo/dashboard")
      if (res.ok) setData(await res.json())
    } catch { /* silent */ }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // Quick fire-and-forget action (result is immediate or not important)
  const run = async (
    jobKey: string,
    url: string,
    method: "POST" | "GET" = "POST",
    successMsg = "Started in background"
  ) => {
    setJobs(j => ({ ...j, [jobKey]: true }))
    try {
      const res = await fetch(url, { method })
      if (res.ok) {
        showToast(successMsg)
        setTimeout(load, 3000)
      } else {
        showToast(`Error: ${res.status}`)
      }
    } catch (e) {
      showToast(`Failed: ${e}`)
    }
    setJobs(j => ({ ...j, [jobKey]: false }))
  }

  // Long-running background job: keeps button in "Working…" state and polls
  // until the given field in /seo/dashboard changes, then reloads.
  const runLong = async (
    jobKey: string,
    postUrl: string,
    pollUrl: string,
    changedFn: (prev: DashboardData, next: DashboardData) => boolean,
    successMsg = "Done!"
  ) => {
    setJobs(j => ({ ...j, [jobKey]: true }))
    try {
      const startRes = await fetch(postUrl, { method: "POST" })
      if (!startRes.ok) {
        showToast(`Error starting: ${startRes.status}`)
        setJobs(j => ({ ...j, [jobKey]: false }))
        return
      }

      showToast("Running in background… this may take 1-3 minutes")

      // Poll every 6 seconds for up to 4 minutes
      const deadline = Date.now() + 4 * 60 * 1000
      let prevData = data
      while (Date.now() < deadline) {
        await new Promise<void>(r => setTimeout(r, 6000))
        try {
          const pollRes = await fetch(pollUrl)
          if (pollRes.ok) {
            const newData: DashboardData = await pollRes.json()
            if (prevData && changedFn(prevData, newData)) {
              setData(newData)
              showToast(successMsg)
              setJobs(j => ({ ...j, [jobKey]: false }))
              return
            }
            prevData = newData
          }
        } catch { /* keep polling */ }
      }

      // Timeout — reload anyway and let user see what we have
      await load()
      showToast("Took longer than expected — check back in a moment")
    } catch (e) {
      showToast(`Failed: ${e}`)
    }
    setJobs(j => ({ ...j, [jobKey]: false }))
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-neutral-600 text-sm">
        Loading SEO data…
      </div>
    )
  }

  if (!data) {
    return (
      <div className="text-center py-16">
        <p className="text-neutral-500 text-sm mb-4">SEO engine not initialised yet.</p>
        <ActionButton
          label="Build Embeddings (first-time setup)"
          variant="primary"
          loading={jobs["embed"]}
          onClick={() => runLong(
            "embed",
            "/api/py/seo/embeddings/rebuild",
            "/api/py/seo/dashboard",
            (_prev, next) => next.embeddings.count > 0,
            "Embeddings built! Reload to see full dashboard."
          )}
        />
      </div>
    )
  }

  const { embeddings, linking, coverage, freshness, scoring, keywords, roadmap } = data

  return (
    <div className="space-y-8 pb-12">

      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-neutral-800 border border-neutral-700 text-neutral-200 text-sm px-4 py-2 rounded-lg shadow-xl">
          {toast}
        </div>
      )}

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-neutral-100">SEO Engine</h1>
          <p className="text-[12px] text-neutral-500 mt-0.5">
            Autonomous topical authority builder for cadialogue.in
          </p>
        </div>
        <div className="flex gap-2">
          <ActionButton
            label="Refresh All"
            loading={jobs["refresh"]}
            onClick={() => { load(); showToast("Refreshed") }}
          />
          <ActionButton
            label="Batch Index URLs"
            variant="primary"
            loading={jobs["batchindex"]}
            onClick={() => run("batchindex", "/api/py/seo/index/batch-submit", "POST",
              "Submitting unindexed URLs to Google + IndexNow…")}
          />
        </div>
      </div>

      {/* ── Authority Score ── */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/30 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-[11px] text-neutral-500 uppercase tracking-wider">Topical Authority Score</p>
            <p className={`text-5xl font-black mt-1 ${gradeColor(coverage.authority_score ?? 0)}`}>
              {fmt(coverage.authority_score, 1)}<span className="text-2xl text-neutral-600">/100</span>
            </p>
          </div>
          <ActionButton
            label="Rebuild Topic Map"
            loading={jobs["topics"]}
            onClick={() => runLong(
              "topics",
              "/api/py/seo/topics/rebuild",
              "/api/py/seo/dashboard",
              (prev, next) => next.coverage.last_updated > (prev.coverage.last_updated ?? 0),
              "Topic map rebuilt! Authority score updated."
            )}
          />
        </div>
        {/* Authority bar */}
        <div className="h-2 w-full rounded-full bg-neutral-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              (coverage.authority_score ?? 0) >= 70 ? "bg-emerald-500"
              : (coverage.authority_score ?? 0) >= 40 ? "bg-amber-400"
              : "bg-red-500"
            }`}
            style={{ width: `${coverage.authority_score ?? 0}%` }}
          />
        </div>
        <p className="text-[10px] text-neutral-600 mt-1">
          {coverage.total_articles} articles across {coverage.total_pillars} topic pillars
          — {coverage.weak_pillars} pillars need more content
        </p>
      </div>

      {/* ── Stats grid ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Internal Links"
          value={fmt(linking.total_links)}
          sub={`Avg ${fmt(linking.avg_outgoing, 1)} out / ${fmt(linking.avg_incoming, 1)} in`}
        />
        <StatCard
          label="Orphan Pages"
          value={fmt(linking.orphan_pages)}
          sub="Zero incoming links"
          accent={linking.orphan_pages > 0}
        />
        <StatCard
          label="SEO Score Avg"
          value={`${fmt(scoring.average_score, 1)}/100`}
          sub={`${scoring.needs_update} articles need work`}
          accent={scoring.average_score < 60}
        />
        <StatCard
          label="Stale Articles"
          value={fmt(freshness.stale_count)}
          sub={`${freshness.warning_count} more approaching stale`}
          accent={freshness.stale_count > 0}
        />
      </div>

      {/* ── Two-column layout ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Left: Internal Linking */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
          <div className="flex items-center justify-between mb-4">
            <SectionHeader
              title="Internal Linking Engine"
              subtitle={`Last rebuilt ${relTime(linking.last_rebuilt)}`}
            />
            <ActionButton
              label="Rebuild Embeddings"
              loading={jobs["embed"]}
              onClick={() => runLong(
                "embed",
                "/api/py/seo/embeddings/rebuild",
                "/api/py/seo/dashboard",
                (prev, next) => next.embeddings.count > 0 && next.embeddings.last_updated > (prev.embeddings.last_updated ?? 0),
                "Embeddings rebuilt!"
              )}
            />
          </div>

          <div className="space-y-2 mb-4">
            {[
              { label: "Total site-wide links", value: fmt(linking.total_links) },
              { label: "Articles embedded",      value: fmt(embeddings.count) },
              { label: "Avg outgoing per page",  value: fmt(linking.avg_outgoing, 1) },
              { label: "Avg incoming per page",  value: fmt(linking.avg_incoming, 1) },
              { label: "Orphan pages",           value: fmt(linking.orphan_pages), warn: linking.orphan_pages > 0 },
            ].map(row => (
              <div key={row.label} className="flex items-center justify-between text-[12px]">
                <span className="text-neutral-500">{row.label}</span>
                <span className={`font-medium tabular-nums ${row.warn ? "text-red-400" : "text-neutral-300"}`}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>

          <div className="flex gap-2 flex-wrap">
            <ActionButton
              label="Find Orphans"
              loading={jobs["orphans"]}
              onClick={async () => {
                setJobs(j => ({ ...j, orphans: true }))
                const res = await fetch("/api/py/seo/link/orphans")
                if (res.ok) {
                  const d = await res.json()
                  showToast(`${d.count} orphan pages found`)
                }
                setJobs(j => ({ ...j, orphans: false }))
              }}
            />
            <ActionButton
              label="Score All Posts"
              loading={jobs["score"]}
              onClick={() => runLong(
                "score",
                "/api/py/seo/scores/rebuild",
                "/api/py/seo/dashboard",
                (prev, next) => next.scoring.articles_scored > 0 && next.scoring.articles_scored !== prev.scoring.articles_scored,
                "All posts scored!"
              )}
            />
          </div>
        </div>

        {/* Right: Content Freshness */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
          <div className="flex items-center justify-between mb-4">
            <SectionHeader
              title="Content Freshness"
              subtitle={`Last scan ${relTime(freshness.last_scan)}`}
            />
            <ActionButton
              label="Scan Now"
              loading={jobs["fresh"]}
              onClick={() => run("fresh", "/api/py/seo/freshness/scan", "POST",
                "Scanning for stale content…")}
            />
          </div>

          {freshness.top_stale?.length > 0 ? (
            <div className="space-y-2">
              {freshness.top_stale.slice(0, 5).map(a => (
                <div key={a.post_id} className="flex items-start justify-between gap-3 text-[12px]">
                  <span className="text-neutral-400 line-clamp-1 flex-1">{a.title || `Post #${a.post_id}`}</span>
                  <span className={`shrink-0 tabular-nums ${a.pct_stale >= 100 ? "text-red-400" : "text-amber-400"}`}>
                    {a.age_days}d ({fmt(a.pct_stale, 0)}%)
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-neutral-600 text-[12px]">
              No stale articles detected. Run a scan to check.
            </p>
          )}

          <div className="mt-4 grid grid-cols-2 gap-2 text-center text-[11px]">
            <div className="rounded-lg bg-red-950/30 border border-red-900/40 py-2">
              <p className="text-red-400 font-bold text-lg">{freshness.stale_count}</p>
              <p className="text-neutral-600">Critical (overdue)</p>
            </div>
            <div className="rounded-lg bg-amber-950/20 border border-amber-900/30 py-2">
              <p className="text-amber-400 font-bold text-lg">{freshness.warning_count}</p>
              <p className="text-neutral-600">Warning (&gt;75%)</p>
            </div>
          </div>
        </div>

        {/* Left: Keyword Easy Wins */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
          <div className="flex items-center justify-between mb-4">
            <SectionHeader
              title="Easy-Win Keywords"
              subtitle="Low difficulty, informational intent — write these next"
            />
            <ActionButton
              label="Discover Keywords"
              loading={jobs["kw"]}
              onClick={() => run("kw", "/api/py/seo/keywords/discover", "POST",
                "Discovering keywords via Google Autocomplete…")}
            />
          </div>

          {keywords.easy_wins?.length > 0 ? (
            <div className="space-y-1.5">
              {keywords.easy_wins.slice(0, 6).map((kw, i) => (
                <div key={i} className="flex items-center justify-between text-[12px]">
                  <span className="text-neutral-300 flex-1 truncate">{kw.kw}</span>
                  <div className="flex gap-3 shrink-0 ml-3">
                    <span className="text-neutral-600 tabular-nums">~{fmt(kw.volume_est)}/mo</span>
                    <span className={`tabular-nums ${kw.difficulty <= 30 ? "text-emerald-400" : "text-amber-400"}`}>
                      KD {kw.difficulty}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-neutral-600 text-[12px]">
              Run keyword discovery to populate this list.
            </p>
          )}
        </div>

        {/* Right: Content Roadmap */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
          <SectionHeader
            title="Content Roadmap"
            subtitle="High-priority articles to write for topical authority gaps"
          />

          {roadmap.top_items?.length > 0 ? (
            <div className="space-y-3">
              {roadmap.top_items.slice(0, 5).map((item, i) => (
                <div key={i} className="text-[12px] border-b border-neutral-800/60 pb-2 last:border-0">
                  <p className="text-neutral-300 font-medium line-clamp-1">{item.title}</p>
                  <div className="flex gap-2 mt-0.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      item.priority === "high"
                        ? "bg-red-900/40 text-red-400"
                        : "bg-neutral-800 text-neutral-500"
                    }`}>{item.priority}</span>
                    <span className="text-neutral-600 text-[10px]">{item.intent}</span>
                    <span className="text-neutral-600 text-[10px] truncate">{item.focus_keyword}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-neutral-600 text-[12px]">
              Run "Rebuild Topic Map" to generate content roadmap.
            </p>
          )}
        </div>
      </div>

      {/* ── Programmatic SEO ── */}
      <ProgrammaticSection jobs={jobs} setJobs={setJobs} showToast={showToast} />
    </div>
  )
}


// ── Programmatic SEO section ──────────────────────────────────────────────────

function ProgrammaticSection({
  jobs, setJobs, showToast
}: {
  jobs: Record<string, boolean>
  setJobs: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  showToast: (m: string) => void
}) {
  const [queue, setQueue]   = useState<any[]>([])
  const [loaded, setLoaded] = useState(false)

  const loadQueue = async () => {
    const res = await fetch("/api/py/seo/programmatic/queue")
    if (res.ok) {
      const d = await res.json()
      setQueue(d.queue || [])
    }
    setLoaded(true)
  }

  useEffect(() => { loadQueue() }, [])

  const generate = async (item: any) => {
    const key = `prog_${item.slug}`
    setJobs(j => ({ ...j, [key]: true }))
    try {
      // POST returns immediately — GPT-4o takes 40-90s which exceeds Render's
      // 30s request timeout if we wait synchronously
      const res = await fetch("/api/py/seo/programmatic/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_type: item.template,
          params: item,
        }),
      })
      if (!res.ok) {
        showToast(`Failed to start generation (${res.status})`)
        setJobs(j => ({ ...j, [key]: false }))
        return
      }

      const { slug } = await res.json()
      showToast("Generating… GPT-4o is writing the article (up to 90s)")

      // Poll status every 4s for up to 3 minutes
      const deadline = Date.now() + 3 * 60 * 1000
      while (Date.now() < deadline) {
        await new Promise<void>(r => setTimeout(r, 4000))
        try {
          const statusRes = await fetch(`/api/py/seo/programmatic/status/${slug}`)
          if (statusRes.ok) {
            const s = await statusRes.json()
            if (s.status === "done") {
              showToast(`✓ Generated: ${s.title} (${s.word_count} words)`)
              loadQueue()
              setJobs(j => ({ ...j, [key]: false }))
              return
            }
            if (s.status === "error") {
              showToast(`Generation failed: ${s.message}`)
              setJobs(j => ({ ...j, [key]: false }))
              return
            }
            // status === "pending" — keep polling
          }
        } catch { /* keep polling */ }
      }

      showToast("Timed out — try again or check Render logs")
    } catch (e) {
      showToast(`Network error: ${e}`)
    }
    setJobs(j => ({ ...j, [key]: false }))
  }

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
      <div className="flex items-center justify-between mb-4">
        <SectionHeader
          title="Programmatic SEO"
          subtitle={`${queue.length} pages queued for generation — scalable long-tail coverage`}
        />
      </div>

      {!loaded ? (
        <p className="text-neutral-600 text-[12px]">Loading queue…</p>
      ) : queue.length === 0 ? (
        <p className="text-neutral-600 text-[12px]">All programmatic pages have been generated.</p>
      ) : (
        <div className="space-y-2">
          {queue.slice(0, 8).map((item, i) => (
            <div key={i} className="flex items-center justify-between gap-4 text-[12px]">
              <div className="flex-1 min-w-0">
                <p className="text-neutral-300 truncate">{item.title}</p>
                <p className="text-neutral-600 text-[10px]">/{item.slug}</p>
              </div>
              <span className="shrink-0 text-[10px] text-neutral-600 bg-neutral-800 px-1.5 py-0.5 rounded">
                {item.template}
              </span>
              <button
                onClick={() => generate(item)}
                disabled={jobs[`prog_${item.slug}`]}
                className="shrink-0 h-6 px-2.5 rounded border border-red-600/40 text-red-400 text-[11px] hover:bg-red-600/10 disabled:opacity-50"
              >
                {jobs[`prog_${item.slug}`] ? "…" : "Generate"}
              </button>
            </div>
          ))}
          {queue.length > 8 && (
            <p className="text-neutral-600 text-[11px]">+{queue.length - 8} more in queue</p>
          )}
        </div>
      )}
    </div>
  )
}
