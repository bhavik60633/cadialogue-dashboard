"use client"

import { useEffect, useState, useCallback, useRef } from "react"

// ─── Types ─────────────────────────────────────────────────────────────────────

interface LibraryTopic {
  id: string
  title: string
  summary: string
  category: string
  sources: { url?: string; publisher?: string }[]
  score: number
  added_by: string
  added_at: string
  promoted_at: string | null
  promoted_to_batch: string | null
}

interface CategoryInfo {
  key: string
  display: string
  emoji: string
  count: number
}

// ─── Category colour map ────────────────────────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  markets:              "text-orange-400  bg-orange-400/8  border-orange-400/20",
  economy:              "text-teal-400    bg-teal-400/8    border-teal-400/20",
  banking:              "text-indigo-400  bg-indigo-400/8  border-indigo-400/20",
  personal_finance:     "text-emerald-400 bg-emerald-400/8 border-emerald-400/20",
  mutual_funds:         "text-cyan-400    bg-cyan-400/8    border-cyan-400/20",
  tax_gst:              "text-red-400     bg-red-400/8     border-red-400/20",
  real_estate:          "text-yellow-400  bg-yellow-400/8  border-yellow-400/20",
  startups:             "text-lime-400    bg-lime-400/8    border-lime-400/20",
  crypto:               "text-violet-400  bg-violet-400/8  border-violet-400/20",
  opinion:              "text-neutral-400 bg-neutral-400/8 border-neutral-400/20",
  chartered_accountant: "text-rose-400    bg-rose-400/8    border-rose-400/20",
  current_affairs:      "text-sky-400     bg-sky-400/8     border-sky-400/20",
  marketing:            "text-pink-400    bg-pink-400/8    border-pink-400/20",
  ai_technology:        "text-purple-400  bg-purple-400/8  border-purple-400/20",
}

function catColor(key: string) {
  return CAT_COLORS[key] ?? "text-neutral-400 bg-neutral-400/8 border-neutral-400/20"
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function TopicsPage() {
  const [categories, setCategories]   = useState<CategoryInfo[]>([])
  const [topics, setTopics]           = useState<LibraryTopic[]>([])
  const [totalCount, setTotalCount]   = useState(0)
  const [activeCategory, setActiveCategory] = useState("")
  const [query, setQuery]             = useState("")
  const [loading, setLoading]         = useState(true)
  const [showModal, setShowModal]     = useState(false)
  const [promotingId, setPromotingId] = useState<string | null>(null)
  const [promotedIds, setPromotedIds] = useState<Set<string>>(new Set())
  const [deletingId, setDeletingId]   = useState<string | null>(null)

  const searchRef = useRef<HTMLInputElement>(null)

  // ── Fetch ────────────────────────────────────────────────────────────────────

  const fetchTopics = useCallback(async (cat: string, q: string) => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (cat) params.set("category", cat)
      if (q)   params.set("q", q)
      const res = await fetch(`/api/py/library/topics?${params}`)
      const data = await res.json()
      setCategories(data.categories ?? [])
      setTopics(data.topics ?? [])
      // total = sum of all category counts
      setTotalCount((data.categories ?? []).reduce((s: number, c: CategoryInfo) => s + c.count, 0))
    } finally {
      setLoading(false)
    }
  }, [])

  // Fetch on category change (immediate) and on initial mount
  const queryRef = useRef(query)
  useEffect(() => { queryRef.current = query }, [query])

  useEffect(() => {
    fetchTopics(activeCategory, queryRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCategory, fetchTopics])

  // ── Debounced search (query only) ─────────────────────────────────────────────

  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeCategoryRef = useRef(activeCategory)
  useEffect(() => { activeCategoryRef.current = activeCategory }, [activeCategory])

  const handleSearch = useCallback((val: string) => {
    setQuery(val)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => fetchTopics(activeCategoryRef.current, val), 350)
  }, [fetchTopics])

  // ── Promote ──────────────────────────────────────────────────────────────────

  const promote = async (topicId: string) => {
    setPromotingId(topicId)
    try {
      const res = await fetch(`/api/py/library/topics/${topicId}/promote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ added_by: "dashboard" }),
      })
      if (!res.ok) throw new Error(await res.text())
      setPromotedIds(prev => new Set([...prev, topicId]))
      // Refresh to update promoted_at display
      await fetchTopics(activeCategory, query)
    } finally {
      setPromotingId(null)
    }
  }

  // ── Delete ───────────────────────────────────────────────────────────────────

  const deleteTopic = async (topicId: string) => {
    if (!confirm("Remove this topic from the library?")) return
    setDeletingId(topicId)
    try {
      await fetch(`/api/py/library/topics/${topicId}`, { method: "DELETE" })
      await fetchTopics(activeCategory, query)
    } finally {
      setDeletingId(null)
    }
  }

  // ── Add topic callback ───────────────────────────────────────────────────────

  const onTopicAdded = () => {
    setShowModal(false)
    fetchTopics(activeCategory, query)
  }

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex gap-6 min-h-[70vh]">

      {/* ── Sidebar ─────────────────────────────────────────────────────────── */}
      <aside className="w-48 shrink-0 space-y-0.5">
        <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-neutral-600">Categories</p>

        {/* All */}
        <SidebarItem
          emoji="📚" label="All topics"
          count={totalCount}
          active={activeCategory === ""}
          onClick={() => setActiveCategory("")}
        />

        <div className="my-2 border-t border-neutral-800/50" />

        {categories.map(cat => (
          <SidebarItem
            key={cat.key}
            emoji={cat.emoji}
            label={cat.display}
            count={cat.count}
            active={activeCategory === cat.key}
            onClick={() => setActiveCategory(cat.key)}
          />
        ))}
      </aside>

      {/* ── Main ────────────────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 space-y-4">

        {/* Top bar */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-neutral-600"
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              ref={searchRef}
              type="text"
              placeholder="Search topics…"
              value={query}
              onChange={e => handleSearch(e.target.value)}
              className="w-full rounded-lg border border-neutral-800/60 bg-neutral-900/60 pl-9 pr-3 py-2 text-[13px] text-neutral-300 placeholder-neutral-600 focus:outline-none focus:border-neutral-700 transition-colors"
            />
          </div>

          <button
            onClick={() => setShowModal(true)}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-red-600 hover:bg-red-500 px-4 py-2 text-[13px] font-semibold text-white transition-colors"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            New Topic
          </button>
        </div>

        {/* Section label */}
        <div className="flex items-center justify-between">
          <h2 className="text-[12px] font-semibold text-neutral-500">
            {activeCategory
              ? (categories.find(c => c.key === activeCategory)?.display ?? activeCategory)
              : "All Topics"}
            {" "}
            <span className="text-neutral-700">({topics.length})</span>
          </h2>
        </div>

        {/* Loading */}
        {loading && (
          <div className="space-y-2">
            {[1,2,3].map(i => (
              <div key={i} className="h-24 rounded-xl border border-neutral-800/50 bg-neutral-900/30 animate-pulse" />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && topics.length === 0 && (
          <EmptyState onAdd={() => setShowModal(true)} category={activeCategory} query={query} />
        )}

        {/* Topic cards */}
        {!loading && topics.map(topic => (
          <TopicCard
            key={topic.id}
            topic={topic}
            promoting={promotingId === topic.id}
            deleting={deletingId === topic.id}
            promoted={promotedIds.has(topic.id) || !!topic.promoted_at}
            onPromote={() => promote(topic.id)}
            onDelete={() => deleteTopic(topic.id)}
          />
        ))}
      </div>

      {/* ── Add topic modal ──────────────────────────────────────────────────── */}
      {showModal && (
        <AddTopicModal
          categories={categories}
          defaultCategory={activeCategory}
          onAdded={onTopicAdded}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  )
}

// ─── Sidebar item ──────────────────────────────────────────────────────────────

function SidebarItem({ emoji, label, count, active, onClick }: {
  emoji: string; label: string; count: number; active: boolean; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-all ${
        active
          ? "bg-neutral-800/70 text-neutral-100"
          : "text-neutral-500 hover:text-neutral-300 hover:bg-neutral-900/60"
      }`}
    >
      <span className="text-[13px] shrink-0">{emoji}</span>
      <span className="flex-1 text-[12px] font-medium truncate">{label}</span>
      {count > 0 && (
        <span className={`text-[10px] tabular-nums shrink-0 ${active ? "text-neutral-400" : "text-neutral-700"}`}>
          {count}
        </span>
      )}
    </button>
  )
}

// ─── Topic card ────────────────────────────────────────────────────────────────

function TopicCard({ topic, promoting, deleting, promoted, onPromote, onDelete }: {
  topic: LibraryTopic
  promoting: boolean
  deleting: boolean
  promoted: boolean
  onPromote: () => void
  onDelete: () => void
}) {
  const relTime = useRelativeTime(topic.added_at)

  return (
    <div className="rounded-xl border border-neutral-800/50 bg-neutral-900/30 hover:border-neutral-700/60 transition-colors group">
      <div className="px-4 pt-4 pb-3 space-y-2">

        {/* Header row */}
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-[14px] font-semibold text-neutral-100 leading-snug flex-1">
            {topic.title}
          </h3>
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Score badge */}
            {topic.score > 0 && (
              <span className="text-[10px] text-neutral-600 tabular-nums px-1.5 py-0.5 rounded border border-neutral-800 bg-neutral-900">
                ★ {topic.score.toFixed(1)}
              </span>
            )}
            {/* Category tag */}
            <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${catColor(topic.category)}`}>
              {topic.category.replace(/_/g, " ")}
            </span>
          </div>
        </div>

        {/* Summary */}
        {topic.summary && (
          <p className="text-[12px] text-neutral-500 leading-relaxed line-clamp-2">
            {topic.summary}
          </p>
        )}

        {/* Sources */}
        {topic.sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {topic.sources.slice(0, 3).map((s, i) => (
              <span key={i} className="text-[10px] text-neutral-700 border border-neutral-800/50 rounded px-1.5 py-0.5">
                {s.publisher || (() => { try { return new URL(s.url || "").hostname } catch { return s.url || "source" } })()}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-neutral-800/40 px-4 py-2 flex items-center gap-3">
        <span className="text-[10px] text-neutral-700 flex-1">
          {topic.added_by === "system" ? "Auto-discovered" : `Added by ${topic.added_by}`}
          {" · "}{relTime}
        </span>

        {/* Promoted indicator */}
        {promoted && (
          <span className="text-[10px] text-emerald-600 flex items-center gap-1">
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
            In queue
          </span>
        )}

        {/* Delete */}
        <button
          onClick={onDelete}
          disabled={deleting}
          className="opacity-0 group-hover:opacity-100 text-[11px] text-neutral-700 hover:text-red-500 transition-all disabled:opacity-30"
          title="Remove from library"
        >
          {deleting ? "…" : "✕"}
        </button>

        {/* Add to queue */}
        {!promoted && (
          <button
            onClick={onPromote}
            disabled={promoting}
            className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-700/60 hover:border-red-500/40 hover:bg-red-500/5 px-3 py-1 text-[11px] text-neutral-400 hover:text-red-400 transition-all disabled:opacity-50"
          >
            {promoting
              ? <span className="h-2.5 w-2.5 rounded-full border border-neutral-600 border-t-neutral-300 animate-spin" />
              : <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
            }
            {promoting ? "Adding…" : "Add to today"}
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onAdd, category, query }: {
  onAdd: () => void; category: string; query: string
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="h-14 w-14 rounded-2xl border border-neutral-800 bg-neutral-900/60 flex items-center justify-center mb-4">
        <svg className="h-6 w-6 text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" />
        </svg>
      </div>
      <p className="text-[14px] font-semibold text-neutral-400 mb-1">
        {query ? `No topics matching "${query}"` : category ? "No topics in this category yet" : "Library is empty"}
      </p>
      <p className="text-[12px] text-neutral-600 mb-4 max-w-xs">
        {query
          ? "Try a different search term or clear the filter."
          : "Add topics manually or generate an article batch — topics will be saved here automatically."}
      </p>
      {!query && (
        <button onClick={onAdd}
          className="inline-flex items-center gap-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 px-4 py-2 text-[12px] font-medium text-neutral-300 transition-colors">
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Add your first topic
        </button>
      )}
    </div>
  )
}

// ─── Add topic modal ───────────────────────────────────────────────────────────

function AddTopicModal({ categories, defaultCategory, onAdded, onClose }: {
  categories: CategoryInfo[]
  defaultCategory: string
  onAdded: () => void
  onClose: () => void
}) {
  const [title, setTitle]     = useState("")
  const [summary, setSummary] = useState("")
  const [category, setCategory] = useState(defaultCategory || "markets")
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState("")

  const submit = async (e?: React.FormEvent | React.MouseEvent) => {
    e?.preventDefault()
    if (!title.trim()) { setError("Title is required"); return }
    setSaving(true); setError("")
    try {
      const res = await fetch("/api/py/library/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim(), summary: summary.trim(), category, added_by: "dashboard" }),
      })
      if (!res.ok) throw new Error(await res.text())
      onAdded()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add topic")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-neutral-800 bg-neutral-950 shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="px-6 py-4 border-b border-neutral-800 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-neutral-100">Add Topic to Library</h2>
          <button onClick={onClose} className="text-neutral-600 hover:text-neutral-300">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={submit} className="px-6 py-5 space-y-4">

          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-[12px] font-medium text-neutral-400">
              Topic title <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="e.g. RBI MPC Rate Decision May 2026"
              autoFocus
              className="w-full rounded-lg border border-neutral-800/60 bg-neutral-900/60 px-3 py-2 text-[13px] text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-neutral-700 transition-colors"
            />
          </div>

          {/* Summary */}
          <div className="space-y-1.5">
            <label className="text-[12px] font-medium text-neutral-400">
              Brief summary <span className="text-neutral-600">(optional)</span>
            </label>
            <textarea
              value={summary}
              onChange={e => setSummary(e.target.value)}
              placeholder="2-3 sentences about what the article should cover…"
              rows={3}
              className="w-full rounded-lg border border-neutral-800/60 bg-neutral-900/60 px-3 py-2 text-[13px] text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-neutral-700 transition-colors resize-none"
            />
          </div>

          {/* Category */}
          <div className="space-y-1.5">
            <label className="text-[12px] font-medium text-neutral-400">Category</label>
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              className="w-full rounded-lg border border-neutral-800/60 bg-neutral-900 px-3 py-2 text-[13px] text-neutral-200 focus:outline-none focus:border-neutral-700 transition-colors"
            >
              {categories.map(cat => (
                <option key={cat.key} value={cat.key}>
                  {cat.emoji} {cat.display}
                </option>
              ))}
            </select>
          </div>

          {error && (
            <p className="text-[12px] text-red-400">{error}</p>
          )}
        </form>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-neutral-800 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-[12px] text-neutral-500 hover:text-neutral-300">
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving || !title.trim()}
            className="px-5 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-[12px] font-semibold text-white transition-colors disabled:opacity-50"
          >
            {saving ? "Saving…" : "Add to Library"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Hook: relative time ───────────────────────────────────────────────────────

function useRelativeTime(iso: string): string {
  const [label, setLabel] = useState("")
  useEffect(() => {
    const update = () => {
      const diff = Date.now() - new Date(iso).getTime()
      const mins = Math.floor(diff / 60000)
      if (mins < 2)   { setLabel("just now"); return }
      if (mins < 60)  { setLabel(`${mins}m ago`); return }
      const hrs = Math.floor(mins / 60)
      if (hrs < 24)   { setLabel(`${hrs}h ago`); return }
      const days = Math.floor(hrs / 24)
      setLabel(`${days}d ago`)
    }
    update()
    const t = setInterval(update, 30000)
    return () => clearInterval(t)
  }, [iso])
  return label
}
