"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import type { PipelineRun, MorningBatch } from "@/lib/pipeline-state"
import { TopicCard } from "@/components/queue/TopicCard"

// ── Types ─────────────────────────────────────────────────────────────────────

interface BatchResponse {
  batch: MorningBatch | null
  runs: PipelineRun[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const ACTIVE_STATUSES = new Set(["generating", "publishing"])

function hasActiveRuns(runs: PipelineRun[]): boolean {
  return runs.some((r) => ACTIVE_STATUSES.has(r.topic_status ?? ""))
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`/api/py${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts?.headers ?? {}) },
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try { msg = (await res.json()).detail ?? msg } catch { /* keep default */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

// ── Spinner ───────────────────────────────────────────────────────────────────

function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

// ── Card skeleton ─────────────────────────────────────────────────────────────

function CardSkeleton({ delay = 0 }: { delay?: number }) {
  return (
    <div
      className="rounded-xl border border-neutral-800/40 bg-neutral-900/30 p-5 flex flex-col gap-4 animate-pulse"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-center gap-2">
        <div className="h-3 w-4 rounded bg-neutral-800" />
        <div className="h-4 w-20 rounded-md bg-neutral-800" />
        <div className="ml-auto h-3 w-16 rounded bg-neutral-800" />
      </div>
      <div className="space-y-2">
        <div className="h-3.5 w-full rounded bg-neutral-800" />
        <div className="h-3.5 w-4/5 rounded bg-neutral-800" />
      </div>
      <div className="flex gap-1.5">
        {[72, 88, 64].map((w) => (
          <div key={w} className="h-5 rounded-md bg-neutral-800/70" style={{ width: w }} />
        ))}
      </div>
      <div className="flex items-center gap-2 border-t border-neutral-800/30 pt-3 mt-1">
        <div className="ml-auto h-7 w-16 rounded-lg bg-neutral-800/60" />
        <div className="h-7 w-24 rounded-lg bg-neutral-800/80" />
      </div>
    </div>
  )
}

// ── Stat tile ─────────────────────────────────────────────────────────────────

function StatTile({
  label, value, color = "text-neutral-100",
}: {
  label: string; value: number; color?: string
}) {
  return (
    <div className="rounded-xl border border-neutral-800/50 bg-neutral-900/30 px-4 py-3.5 text-center">
      <p className={`text-2xl font-bold tabular-nums ${color}`}>{value}</p>
      <p className="mt-1 text-[10px] font-medium uppercase tracking-widest text-neutral-600">{label}</p>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onDiscover, busy }: { onDiscover: () => void; busy: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-neutral-800/50 py-20 px-6 text-center">
      <div className="mb-5 rounded-2xl border border-neutral-800 bg-neutral-900/60 p-5">
        <svg className="h-9 w-9 text-neutral-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.2}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 01-2.25 2.25M16.5 7.5V18a2.25 2.25 0 002.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 002.25 2.25h13.5M6 7.5h3v3H6v-3z"
          />
        </svg>
      </div>
      <h3 className="text-[14px] font-semibold text-neutral-200">No topics queued for today</h3>
      <p className="mt-2 max-w-sm text-[12px] text-neutral-600 leading-relaxed">
        Pull the latest finance headlines from NewsAPI, score them with Claude, and get{" "}
        <strong className="text-neutral-400 font-medium">10 ranked topics</strong> ready to review in under 30 seconds.
      </p>
      <button
        onClick={onDiscover}
        disabled={busy}
        className="mt-6 inline-flex items-center gap-2 rounded-lg bg-red-600 hover:bg-red-500 px-5 py-2.5 text-[13px] font-semibold text-white transition-colors disabled:opacity-50 cursor-pointer"
      >
        {busy ? <><Spinner className="h-3.5 w-3.5" /> Discovering…</> : "Discover Today's Topics"}
      </button>
      <p className="mt-4 text-[11px] text-neutral-700">
        Also runs automatically at 7:00 AM IST via GitHub Actions
      </p>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function QueuePage() {
  const [data, setData]           = useState<BatchResponse>({ batch: null, runs: [] })
  const [loading, setLoading]     = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const timerRef                  = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchBatch = useCallback(async (): Promise<BatchResponse | null> => {
    try {
      const result = await apiFetch<BatchResponse>("/batches/today")
      setData(result)
      setError(null)
      return result
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load batch")
      return null
    }
  }, [])

  // Initial load
  useEffect(() => {
    fetchBatch().finally(() => setLoading(false))
  }, [fetchBatch])

  // Adaptive polling
  useEffect(() => {
    const isActive = hasActiveRuns(data.runs) || discovering
    timerRef.current = setTimeout(async () => {
      const result = await fetchBatch()
      if (discovering && result && result.runs.length > 0) setDiscovering(false)
    }, isActive ? 4_000 : 30_000)

    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [data, discovering, fetchBatch])

  async function handleRefresh() {
    setRefreshing(true)
    setError(null)
    try {
      const res = await apiFetch<{ status: string; batch_id: string }>(
        "/batches/today/refresh", { method: "POST" }
      )
      if (res.status === "started") setDiscovering(true)
      await fetchBatch()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start discovery")
    } finally {
      setRefreshing(false)
    }
  }

  async function handleApprove(runId: string) {
    await apiFetch(`/runs/${runId}/approve`, { method: "POST" })
    await fetchBatch()
  }

  async function handleReject(runId: string) {
    await apiFetch(`/runs/${runId}/reject`, { method: "POST" })
    await fetchBatch()
  }

  async function handleGenerate(runId: string) {
    await apiFetch(`/runs/${runId}/generate`, { method: "POST" })
    await fetchBatch()
  }

  // ── Derived ──────────────────────────────────────────────────────────────

  const { batch, runs } = data
  const pendingCount   = runs.filter((r) => r.topic_status === "pending").length
  const approvedCount  = runs.filter((r) => r.topic_status === "approved").length
  const activeCount    = runs.filter((r) => ACTIVE_STATUSES.has(r.topic_status ?? "")).length
  const doneCount      = runs.filter((r) => r.topic_status === "published").length
  const failedCount    = runs.filter((r) => r.topic_status === "failed").length
  const isDiscovering  = discovering || refreshing
  const showSkeletons  = loading || (isDiscovering && runs.length === 0)

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-7">

      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-neutral-100 tracking-tight">Today's Queue</h1>
          <p className="mt-1 text-[13px] text-neutral-500">
            {batch
              ? `${batch.date} · ${runs.length} topic${runs.length !== 1 ? "s" : ""} discovered`
              : "Pull today's top finance topics for your team to review"}
          </p>
        </div>

        <button
          onClick={handleRefresh}
          disabled={isDiscovering || loading}
          className="
            shrink-0 inline-flex items-center gap-2 rounded-lg bg-red-600 hover:bg-red-500
            px-4 py-2.5 text-[13px] font-semibold text-white transition-colors
            disabled:opacity-50 cursor-pointer
            focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500
          "
        >
          {isDiscovering ? (
            <>
              <Spinner />
              {discovering ? "Discovering…" : "Starting…"}
            </>
          ) : (
            <>
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              {runs.length > 0 ? "Refresh Topics" : "Discover Topics"}
            </>
          )}
        </button>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="flex items-center gap-3 rounded-xl border border-red-900/40 bg-red-950/20 px-4 py-3">
          <svg className="h-4 w-4 shrink-0 text-red-500" viewBox="0 0 16 16" fill="currentColor">
            <path fillRule="evenodd" d="M8 15A7 7 0 108 1a7 7 0 000 14zm.75-10.25a.75.75 0 00-1.5 0v3.5a.75.75 0 001.5 0v-3.5zm-.75 6a.875.875 0 100-1.75.875.875 0 000 1.75z" />
          </svg>
          <p className="text-[12px] text-red-400 flex-1">{error}</p>
          <button onClick={() => setError(null)} className="text-red-700 hover:text-red-500 transition-colors text-sm">✕</button>
        </div>
      )}

      {/* ── Stats ── */}
      {runs.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
          <StatTile label="Pending"    value={pendingCount}  />
          <StatTile label="Approved"   value={approvedCount} color="text-sky-400"     />
          <StatTile label="Generating" value={activeCount}   color="text-amber-400"   />
          <StatTile label="Published"  value={doneCount}     color="text-emerald-400" />
          <StatTile label="Failed"     value={failedCount}   color={failedCount > 0 ? "text-red-400" : "text-neutral-100"} />
        </div>
      )}

      {/* ── Skeletons ── */}
      {showSkeletons && (
        <div className="grid gap-3.5 sm:grid-cols-2">
          {Array.from({ length: 10 }).map((_, i) => (
            <CardSkeleton key={i} delay={i * 40} />
          ))}
        </div>
      )}

      {/* ── Empty state ── */}
      {!loading && !isDiscovering && runs.length === 0 && (
        <EmptyState onDiscover={handleRefresh} busy={isDiscovering} />
      )}

      {/* ── Grid ── */}
      {!loading && runs.length > 0 && (
        <>
          {isDiscovering && (
            <p className="flex items-center gap-2 text-[12px] text-amber-400/70">
              <Spinner className="h-3 w-3" />
              Discovering new topics — list will refresh shortly…
            </p>
          )}

          <div className="grid gap-3.5 sm:grid-cols-2">
            {runs.map((run, i) => (
              <TopicCard
                key={run.id}
                run={run}
                index={i}
                onApprove={handleApprove}
                onReject={handleReject}
                onGenerate={handleGenerate}
              />
            ))}
          </div>

          {/* Footer meta */}
          <div className="flex items-center justify-between pt-1">
            <p className="text-[11px] text-neutral-700">
              Auto-refreshes every {hasActiveRuns(runs) ? "4" : "30"}s
            </p>
            {batch?.created_at && (
              <p className="text-[11px] text-neutral-700">
                Discovered{" "}
                {new Date(batch.created_at).toLocaleTimeString("en-IN", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
