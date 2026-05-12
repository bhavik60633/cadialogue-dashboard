"use client"

import { useState } from "react"
import Link from "next/link"
import type { PipelineRun, TopicStatus } from "@/lib/pipeline-state"

// ── Category config ────────────────────────────────────────────────────────────

const CATEGORY_DISPLAY: Record<string, string> = {
  india_market:        "India Market",
  global_market:       "Global Market",
  crypto:              "Crypto",
  regulation:          "Regulation",
  personal_finance:    "Personal Finance",
  economy:             "Economy",
  banking:             "Banking",
  mutual_funds:        "Mutual Funds",
  tax_gst:             "Tax & GST",
  real_estate:         "Real Estate",
  startups:            "Startups",
  chartered_accountant:"CA",
  current_affairs:     "Current Affairs",
  marketing:           "Marketing",
  ai_technology:       "AI & Technology",
}

const CATEGORY_COLORS: Record<string, string> = {
  india_market:        "text-orange-400 bg-orange-400/8 border-orange-400/20",
  global_market:       "text-blue-400 bg-blue-400/8 border-blue-400/20",
  crypto:              "text-violet-400 bg-violet-400/8 border-violet-400/20",
  regulation:          "text-amber-400 bg-amber-400/8 border-amber-400/20",
  personal_finance:    "text-emerald-400 bg-emerald-400/8 border-emerald-400/20",
  economy:             "text-teal-400 bg-teal-400/8 border-teal-400/20",
  banking:             "text-indigo-400 bg-indigo-400/8 border-indigo-400/20",
  mutual_funds:        "text-cyan-400 bg-cyan-400/8 border-cyan-400/20",
  tax_gst:             "text-red-400 bg-red-400/8 border-red-400/20",
  real_estate:         "text-yellow-400 bg-yellow-400/8 border-yellow-400/20",
  startups:            "text-lime-400 bg-lime-400/8 border-lime-400/20",
  chartered_accountant:"text-rose-400 bg-rose-400/8 border-rose-400/20",
  current_affairs:     "text-sky-400 bg-sky-400/8 border-sky-400/20",
  marketing:           "text-pink-400 bg-pink-400/8 border-pink-400/20",
  ai_technology:       "text-purple-400 bg-purple-400/8 border-purple-400/20",
}

// ── Status config ──────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<TopicStatus, {
  label: string; dotColor: string; textColor: string; pulse?: boolean
}> = {
  pending:       { label: "Pending",         dotColor: "bg-neutral-600",   textColor: "text-neutral-500"  },
  approved:      { label: "Approved",        dotColor: "bg-sky-500",       textColor: "text-sky-400"      },
  rejected:      { label: "Rejected",        dotColor: "bg-red-500",       textColor: "text-red-500"      },
  generating:    { label: "Generating",      dotColor: "bg-amber-400",     textColor: "text-amber-400",  pulse: true },
  article_ready: { label: "Article Ready",   dotColor: "bg-blue-400",      textColor: "text-blue-400"     },
  images_ready:  { label: "Images Ready",    dotColor: "bg-blue-300",      textColor: "text-blue-300"     },
  publishing:    { label: "Publishing",      dotColor: "bg-amber-400",     textColor: "text-amber-400",  pulse: true },
  published:     { label: "Published",       dotColor: "bg-emerald-500",   textColor: "text-emerald-400"  },
  failed:        { label: "Failed",          dotColor: "bg-red-500",       textColor: "text-red-400"      },
}

// ── Spinner ────────────────────────────────────────────────────────────────────

function Spinner({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface TopicCardProps {
  run: PipelineRun
  index: number
  onApprove:  (runId: string) => Promise<void>
  onReject:   (runId: string) => Promise<void>
  onGenerate: (runId: string) => Promise<void>
}

export function TopicCard({ run, index, onApprove, onReject, onGenerate }: TopicCardProps) {
  const [busy, setBusy]         = useState<"approve" | "reject" | "generate" | null>(null)
  const [expanded, setExpanded] = useState(false)

  const status    = (run.topic_status ?? "pending") as TopicStatus
  const cfg       = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending
  const meta      = run.topic_meta
  const category  = meta?.category ?? "global_market"
  const catColor  = CATEGORY_COLORS[category] ?? "text-neutral-500 bg-neutral-800/40 border-neutral-700/30"
  const catLabel  = CATEGORY_DISPLAY[category] ?? category
  const score     = meta?.score ?? 0
  const keywords  = meta?.keywords ?? []
  const isActive  = status === "generating" || status === "publishing"
  const isRejected = status === "rejected"

  async function handle(action: "approve" | "reject" | "generate" | "retry") {
    setBusy(action === "retry" ? "approve" : action)
    try {
      if (action === "approve") {
        await onApprove(run.id)
      } else if (action === "reject") {
        await onReject(run.id)
      } else if (action === "generate") {
        await onGenerate(run.id)
      } else if (action === "retry") {
        // Reset failed → approved, then immediately start generating
        await onApprove(run.id)
        await onGenerate(run.id)
      }
    } finally {
      setBusy(null)
    }
  }

  return (
    <div
      className={`
        group relative flex flex-col rounded-xl border bg-neutral-900/50
        transition-all duration-200 overflow-hidden
        ${isRejected
          ? "border-neutral-800/30 opacity-45"
          : "border-neutral-800/60 hover:border-neutral-700/60"}
        ${status === "published"  ? "border-emerald-900/30" : ""}
        ${status === "failed"     ? "border-red-900/30"     : ""}
        ${isActive                ? "border-amber-900/30"   : ""}
      `}
    >
      {/* Active pulse bar at top */}
      {isActive && (
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-500/60 to-transparent animate-pulse" />
      )}
      {status === "published" && (
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-emerald-500/40 to-transparent" />
      )}

      <div className="p-5 flex flex-col gap-3.5 flex-1">

        {/* ── Top row ── */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-neutral-700 tabular-nums">
            {String(index + 1).padStart(2, "0")}
          </span>

          <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${catColor}`}>
            {catLabel}
          </span>

          {/* Score */}
          <span
            className={`text-[11px] font-mono font-bold tabular-nums ml-0.5
              ${score >= 80 ? "text-emerald-400" : score >= 65 ? "text-amber-400" : "text-neutral-600"}
            `}
            title={`Relevance score: ${score}/100`}
          >
            {score.toFixed(0)}
          </span>

          {/* Status — right */}
          <div className="ml-auto flex items-center gap-1.5 shrink-0">
            <span className={`h-1.5 w-1.5 rounded-full ${cfg.dotColor} ${cfg.pulse ? "animate-pulse" : ""}`} />
            <span className={`text-[11px] font-medium ${cfg.textColor}`}>{cfg.label}</span>
          </div>
        </div>

        {/* ── Title ── */}
        <h3 className="text-[13px] font-semibold leading-snug text-neutral-100 tracking-tight">
          {meta?.title ?? run.topic ?? "Untitled"}
        </h3>

        {/* ── Summary ── */}
        {meta?.summary && (
          <p className={`text-[12px] leading-relaxed text-neutral-500 ${expanded ? "" : "line-clamp-2"}`}>
            {meta.summary}
          </p>
        )}

        {/* ── Keywords ── */}
        {keywords.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {keywords.map((kw) => (
              <span
                key={kw}
                className="rounded-md bg-neutral-800/60 border border-neutral-800/40 px-1.5 py-0.5 text-[10px] font-mono text-neutral-600"
              >
                {kw}
              </span>
            ))}
          </div>
        )}

        {/* ── Sources ── */}
        {meta?.sources && meta.sources.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {meta.sources.slice(0, 4).map((src, i) => (
              <a
                key={i}
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-[10px] text-neutral-700 hover:text-neutral-400 transition-colors"
              >
                <span className="h-1 w-1 rounded-full bg-neutral-700" />
                {src.publisher || "Source"}
              </a>
            ))}
            {meta.sources.length > 4 && (
              <span className="text-[10px] text-neutral-800">
                +{meta.sources.length - 4} more
              </span>
            )}
          </div>
        )}

        {/* ── Word count ── */}
        {run.article_word_count ? (
          <p className="text-[10px] font-mono text-neutral-700 tabular-nums">
            {run.article_word_count.toLocaleString()} words
          </p>
        ) : null}

        {/* ── Error ── */}
        {status === "failed" && run.error && (
          <p className="rounded-lg border border-red-900/30 bg-red-950/20 px-3 py-2 text-[11px] font-mono text-red-500/80 leading-relaxed">
            {run.error.length > 130 ? run.error.slice(0, 130) + "…" : run.error}
          </p>
        )}
      </div>

      {/* ── Action bar ── */}
      <div className="px-5 pb-4 pt-2 flex items-center gap-2 border-t border-neutral-800/40 flex-wrap">
        {/* Show more toggle */}
        <button
          onClick={() => setExpanded((e) => !e)}
          className="mr-auto text-[10px] text-neutral-700 hover:text-neutral-500 transition-colors cursor-pointer"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {expanded ? "↑ less" : "↓ more"}
        </button>

        {/* pending */}
        {status === "pending" && (
          <>
            <button
              onClick={() => handle("reject")}
              disabled={busy !== null}
              className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-800/60 px-3 py-1.5 text-[12px] text-neutral-500 hover:text-red-400 hover:border-red-900/40 disabled:opacity-40 transition-all cursor-pointer"
            >
              {busy === "reject" ? <Spinner className="h-3 w-3" /> : null}
              Reject
            </button>
            <button
              onClick={() => handle("approve")}
              disabled={busy !== null}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-40 transition-all cursor-pointer"
            >
              {busy === "approve" ? <Spinner className="h-3 w-3" /> : null}
              Approve
            </button>
          </>
        )}

        {/* approved */}
        {status === "approved" && (
          <button
            onClick={() => handle("generate")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 hover:bg-red-500 px-4 py-1.5 text-[12px] font-semibold text-white disabled:opacity-40 transition-all cursor-pointer"
          >
            {busy === "generate"
              ? <><Spinner className="h-3 w-3" /> Starting…</>
              : "Generate Article →"
            }
          </button>
        )}

        {/* rejected */}
        {status === "rejected" && (
          <button
            onClick={() => handle("approve")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-800/60 px-3 py-1.5 text-[12px] text-neutral-600 hover:text-sky-400 hover:border-sky-900/40 disabled:opacity-40 transition-all cursor-pointer"
          >
            {busy === "approve" ? <Spinner className="h-3 w-3" /> : null}
            Reconsider
          </button>
        )}

        {/* generating / publishing */}
        {isActive && (
          <span className={`inline-flex items-center gap-2 text-[12px] ${cfg.textColor}`}>
            <Spinner />
            {status === "generating" ? "Writing article…" : "Publishing…"}
          </span>
        )}

        {/* article_ready / images_ready */}
        {(status === "article_ready" || status === "images_ready") && (
          <Link
            href={`/dashboard/runs/${run.id}/article`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 px-4 py-1.5 text-[12px] font-medium text-white transition-all"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909" />
            </svg>
            {status === "images_ready" ? "View Images →" : "Add Images →"}
          </Link>
        )}

        {/* published */}
        {status === "published" && (
          <div className="flex items-center gap-2">
            <Link
              href={`/dashboard/runs/${run.id}/article`}
              className="rounded-lg border border-neutral-800/60 px-3 py-1.5 text-[12px] text-neutral-500 hover:text-neutral-200 hover:border-neutral-700 transition-all"
            >
              Add Images
            </Link>
            {run.wp_post_url && (
              <a
                href={run.wp_post_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700/70 hover:bg-emerald-600 px-4 py-1.5 text-[12px] font-medium text-white transition-all"
              >
                View Live
                <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={1.5}>
                  <path d="M2.5 2.5h7m0 0v7m0-7L2.5 9.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
            )}
          </div>
        )}

        {/* failed */}
        {status === "failed" && (
          <button
            onClick={() => handle("retry")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-1.5 text-[12px] text-amber-400 hover:bg-amber-900/30 disabled:opacity-40 transition-all cursor-pointer"
          >
            {busy === "approve" ? <Spinner className="h-3 w-3" /> : (
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
              </svg>
            )}
            Retry Generation
          </button>
        )}
      </div>
    </div>
  )
}
