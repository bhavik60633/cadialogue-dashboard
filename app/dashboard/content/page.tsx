"use client"

/**
 * Instagram Shorts / Reels Content Generator
 * ─────────────────────────────────────────────────────────────────────────────
 * Fetches top 10 latest world news stories from NewsAPI and uses GPT-4o to
 * write explosive 30-second Instagram Reels scripts with viral hook formulas.
 *
 * Cached for 1 hour server-side — "Refresh" forces a fresh generation.
 */

import { useEffect, useState } from "react"

// ── Types ────────────────────────────────────────────────────────────────────

type Headline = {
  title: string
  description: string
  source: string
  url: string
  published_at: string
  image_url: string
}

type ShortsScript = {
  headline: Headline
  hook_style: "BREAKING" | "SHOCKING" | "CURIOSITY" | "PERSONAL" | "CONTRAST" | "CONTROVERSY" | "QUESTION"
  hook: string
  story: string
  impact: string
  cta: string
  full_script: string
  word_count: number
  estimated_seconds: number
}

type ShortsResponse = {
  generated_at: string
  total: number
  scripts: ShortsScript[]
  from_cache: boolean
  cache_expires_in: number
}

// ── Hook style config ────────────────────────────────────────────────────────

const HOOK_META: Record<string, { label: string; color: string; emoji: string }> = {
  BREAKING:    { label: "Breaking",    color: "bg-red-500/20 text-red-300 border-red-500/30",     emoji: "🔴" },
  SHOCKING:    { label: "Shocking",    color: "bg-orange-500/20 text-orange-300 border-orange-500/30", emoji: "⚡" },
  CURIOSITY:   { label: "Curiosity",   color: "bg-violet-500/20 text-violet-300 border-violet-500/30", emoji: "🔍" },
  PERSONAL:    { label: "Personal",    color: "bg-blue-500/20 text-blue-300 border-blue-500/30",   emoji: "👤" },
  CONTRAST:    { label: "Contrast",    color: "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",   emoji: "🌓" },
  CONTROVERSY: { label: "Controversy", color: "bg-amber-500/20 text-amber-300 border-amber-500/30", emoji: "🔥" },
  QUESTION:    { label: "Question",    color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30", emoji: "❓" },
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso?: string): string {
  if (!iso) return "—"
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)   return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function wordToSeconds(wc: number): string {
  const s = Math.round(wc / 2.6)
  return `${s}s`
}

// ── Copy button ──────────────────────────────────────────────────────────────

function CopyButton({ text, label = "Copy script" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold transition-all border ${
        copied
          ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
          : "bg-neutral-800 text-neutral-300 border-neutral-700 hover:bg-neutral-700 hover:text-white"
      }`}
    >
      {copied ? (
        <>
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          Copied!
        </>
      ) : (
        <>
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.375" />
          </svg>
          {label}
        </>
      )}
    </button>
  )
}

// ── Script card ───────────────────────────────────────────────────────────────

function ScriptCard({ script, index }: { script: ShortsScript; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const meta = HOOK_META[script.hook_style] ?? HOOK_META["BREAKING"]

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 overflow-hidden transition-colors hover:border-neutral-700">
      {/* ── Header ── */}
      <div className="flex items-start gap-3 p-4 pb-3">
        {/* News image */}
        {script.headline.image_url ? (
          <img
            src={script.headline.image_url}
            alt=""
            className="w-16 h-16 rounded-lg object-cover shrink-0 border border-neutral-800"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none" }}
          />
        ) : (
          <div className="w-16 h-16 rounded-lg bg-neutral-800 shrink-0 flex items-center justify-center text-2xl">
            📰
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-[10px] text-neutral-500 font-medium uppercase tracking-wider">
              #{index + 1} · {script.headline.source}
            </span>
            <span className="text-[10px] text-neutral-600">
              {timeAgo(script.headline.published_at)}
            </span>
          </div>
          <p className="text-[13px] font-semibold text-neutral-100 line-clamp-2 leading-snug">
            {script.headline.title}
          </p>
        </div>
      </div>

      {/* ── Badges ── */}
      <div className="px-4 pb-3 flex items-center gap-2 flex-wrap">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${meta.color}`}>
          {meta.emoji} {meta.label}
        </span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-neutral-800 text-neutral-400 border border-neutral-700">
          ⏱ ~{wordToSeconds(script.word_count)} ({script.word_count} words)
        </span>
        {script.headline.url && (
          <a
            href={script.headline.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-neutral-800 text-neutral-400 border border-neutral-700 hover:text-neutral-200 transition-colors"
          >
            Source ↗
          </a>
        )}
      </div>

      {/* ── Script sections ── */}
      <div className="px-4 pb-3 space-y-2.5">
        {/* Hook */}
        <div className="rounded-lg bg-red-500/8 border border-red-500/15 p-3">
          <div className="text-[9px] font-bold uppercase tracking-widest text-red-400/70 mb-1.5">
            🎣 HOOK · 3–5 sec
          </div>
          <p className="text-[13px] text-neutral-100 font-medium leading-snug">{script.hook}</p>
        </div>

        {/* Story */}
        <div className="rounded-lg bg-neutral-800/60 border border-neutral-700/40 p-3">
          <div className="text-[9px] font-bold uppercase tracking-widest text-neutral-500 mb-1.5">
            📖 STORY · 15 sec
          </div>
          <p className="text-[13px] text-neutral-300 leading-snug">{script.story}</p>
        </div>

        {/* Impact */}
        <div className="rounded-lg bg-amber-500/8 border border-amber-500/15 p-3">
          <div className="text-[9px] font-bold uppercase tracking-widest text-amber-400/70 mb-1.5">
            💥 IMPACT · 7 sec
          </div>
          <p className="text-[13px] text-neutral-200 leading-snug">{script.impact}</p>
        </div>

        {/* CTA */}
        <div className="rounded-lg bg-emerald-500/8 border border-emerald-500/15 p-3">
          <div className="text-[9px] font-bold uppercase tracking-widest text-emerald-400/70 mb-1.5">
            📲 CTA · 3 sec
          </div>
          <p className="text-[13px] text-emerald-300 font-semibold leading-snug">{script.cta}</p>
        </div>
      </div>

      {/* ── Full script toggle ── */}
      <div className="px-4 pb-4">
        <button
          onClick={() => setExpanded(p => !p)}
          className="text-[11px] text-neutral-500 hover:text-neutral-300 transition-colors mb-2"
        >
          {expanded ? "▲ Hide full script" : "▼ View full script (copy-ready)"}
        </button>

        {expanded && (
          <div className="rounded-lg bg-neutral-950 border border-neutral-800 p-3 mt-2">
            <pre className="text-[12px] text-neutral-200 whitespace-pre-wrap font-mono leading-relaxed">
              {script.full_script}
            </pre>
          </div>
        )}
      </div>

      {/* ── Actions ── */}
      <div className="px-4 pb-4 flex items-center gap-2 border-t border-neutral-800 pt-3">
        <CopyButton text={script.full_script} label="Copy full script" />
        <CopyButton text={script.hook} label="Copy hook only" />
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function ContentPage() {
  const [data, setData]           = useState<ShortsResponse | null>(null)
  const [loading, setLoading]     = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [filter, setFilter]       = useState<string>("ALL")

  async function load(forceRefresh = false) {
    if (forceRefresh) setRefreshing(true)
    else setLoading(true)
    setError(null)

    try {
      const endpoint = forceRefresh
        ? "/api/py/content/shorts/refresh"
        : "/api/py/content/shorts"
      const res = await fetch(endpoint, {
        method: forceRefresh ? "POST" : "GET",
        cache: "no-store",
      })
      if (!res.ok) {
        const body = await res.text()
        throw new Error(`HTTP ${res.status}: ${body}`)
      }
      setData(await res.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => { load() }, [])

  const hookStyles = data
    ? ["ALL", ...Array.from(new Set(data.scripts.map(s => s.hook_style)))]
    : ["ALL"]

  const filtered = data
    ? (filter === "ALL" ? data.scripts : data.scripts.filter(s => s.hook_style === filter))
    : []

  return (
    <div className="max-w-5xl pb-24">
      {/* ── Header ── */}
      <header className="mb-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[20px] font-semibold text-neutral-100 flex items-center gap-2">
              📱 Instagram Shorts Generator
            </h1>
            <p className="text-[13px] text-neutral-500 mt-1">
              Top 10 latest world news → 30-second Instagram Reel scripts with viral hooks.
              GPT-4o writes each script. Results cached 1 hour — refresh for the latest news.
            </p>
          </div>

          <button
            onClick={() => load(true)}
            disabled={refreshing || loading}
            className="shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[13px] font-semibold transition-colors"
          >
            {refreshing ? (
              <>
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Generating…
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
                {data ? "Refresh News" : "Generate Scripts"}
              </>
            )}
          </button>
        </div>

        {/* Cache status */}
        {data && (
          <div className="mt-3 flex items-center gap-3 text-[11px]">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border ${
              data.from_cache
                ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
            }`}>
              {data.from_cache ? "⚡ Cached result" : "✓ Fresh from NewsAPI + GPT-4o"}
            </span>
            <span className="text-neutral-600">
              Generated {new Date(data.generated_at).toLocaleTimeString()}
              {data.from_cache && data.cache_expires_in > 0 && ` · expires in ${Math.ceil(data.cache_expires_in / 60)}m`}
            </span>
            <span className="text-neutral-600">· {data.total} stories</span>
          </div>
        )}
      </header>

      {/* ── Error ── */}
      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 mb-6">
          <p className="text-[13px] text-red-300 font-medium mb-1">Failed to generate scripts</p>
          <p className="text-[12px] text-red-400/80">{error}</p>
          <button
            onClick={() => load(true)}
            className="mt-3 text-[12px] text-red-400 hover:text-red-300 underline"
          >
            Try again →
          </button>
        </div>
      )}

      {/* ── Loading skeleton ── */}
      {(loading || refreshing) && (
        <div className="space-y-4">
          {loading && (
            <div className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6 text-center">
              <div className="flex items-center justify-center gap-3 text-neutral-400">
                <svg className="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="text-[14px]">
                  {loading ? "Fetching latest world news and writing scripts…" : "Refreshing with today's latest news…"}
                </span>
              </div>
              <p className="text-[12px] text-neutral-600 mt-2">
                GPT-4o is writing 10 scripts — usually takes 20–40 seconds
              </p>
            </div>
          )}
          {refreshing && data && (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-[12px] text-amber-400">
              ⚡ Fetching the very latest news and regenerating all 10 scripts…
            </div>
          )}
        </div>
      )}

      {/* ── Empty state (after load, no data, no error) ── */}
      {!loading && !error && !data && (
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-10 text-center">
          <div className="text-4xl mb-3">📱</div>
          <div className="text-[14px] font-semibold text-neutral-200 mb-1">Ready to generate</div>
          <div className="text-[12px] text-neutral-500">
            Click "Generate Scripts" to fetch the top 10 world news stories and create
            Instagram-ready 30-second Reel scripts with viral hooks.
          </div>
          <button
            onClick={() => load(true)}
            className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-[13px] font-semibold transition-colors"
          >
            Generate Scripts →
          </button>
        </div>
      )}

      {/* ── Hook style filter ── */}
      {data && data.scripts.length > 0 && !loading && (
        <div className="flex items-center gap-2 mb-5 flex-wrap">
          {hookStyles.map(style => (
            <button
              key={style}
              onClick={() => setFilter(style)}
              className={`px-3 py-1 rounded-full text-[11px] font-semibold border transition-colors ${
                filter === style
                  ? "bg-neutral-100 text-neutral-900 border-neutral-100"
                  : "bg-transparent text-neutral-400 border-neutral-700 hover:border-neutral-500 hover:text-neutral-200"
              }`}
            >
              {style === "ALL"
                ? `All (${data.scripts.length})`
                : `${HOOK_META[style]?.emoji} ${HOOK_META[style]?.label} (${data.scripts.filter(s => s.hook_style === style).length})`
              }
            </button>
          ))}
        </div>
      )}

      {/* ── Script cards ── */}
      {!loading && filtered.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {filtered.map((script, i) => (
            <ScriptCard key={i} script={script} index={data!.scripts.indexOf(script)} />
          ))}
        </div>
      )}

      {/* ── Usage note ── */}
      {data && (
        <div className="mt-8 rounded-lg border border-neutral-800 bg-neutral-900/30 p-4">
          <p className="text-[11px] text-neutral-500 leading-relaxed">
            <span className="font-semibold text-neutral-400">💡 How to use:</span> Each script
            is structured as Hook → Story → Impact → CTA. Film in 9:16 vertical (Reels format).
            Speak naturally at ~150 words/min. Add captions with CapCut or InShot. Post between
            6–9pm IST for best engagement. Scripts are based on real news — always verify figures
            before posting.
          </p>
        </div>
      )}
    </div>
  )
}
