"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"

// ── Types ──────────────────────────────────────────────────────────────────────

interface WpPost {
  id: number
  date: string
  modified: string
  link: string
  status: "publish" | "draft" | "private" | "pending" | "trash"
  slug: string
  title: { rendered: string }
  excerpt: { rendered: string }
  categories: number[]
  _embedded?: {
    "wp:term"?: Array<Array<{ id: number; name: string; taxonomy: string }>>
    "wp:featuredmedia"?: Array<{ source_url: string; alt_text: string }>
  }
}

const STATUS_TABS = [
  { key: "any", label: "All" },
  { key: "publish", label: "Published" },
  { key: "draft", label: "Draft" },
  { key: "trash", label: "Trash" },
] as const

const STATUS_BADGE: Record<string, string> = {
  publish: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
  draft:   "bg-yellow-500/15 text-yellow-400 border border-yellow-500/20",
  private: "bg-purple-500/15 text-purple-400 border border-purple-500/20",
  pending: "bg-blue-500/15 text-blue-400 border border-blue-500/20",
  trash:   "bg-neutral-500/15 text-neutral-400 border border-neutral-500/20",
}

function stripHtml(html: string): string {
  return html.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&#8217;/g, "'").replace(/&#8216;/g, "'").trim()
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
}

function getCategoryNames(post: WpPost): string {
  const terms = post._embedded?.["wp:term"]?.[0] ?? []
  const cats = terms.filter((t) => t.taxonomy === "category").map((t) => t.name)
  return cats.join(", ") || "—"
}

// ── Delete confirmation modal ──────────────────────────────────────────────────

function DeleteModal({
  post,
  onConfirm,
  onCancel,
  deleting,
}: {
  post: WpPost
  onConfirm: () => void
  onCancel: () => void
  deleting: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative z-10 w-full max-w-md rounded-xl border border-neutral-700 bg-[#111113] p-6 shadow-2xl">
        <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-red-500/10 border border-red-500/20">
          <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
        </div>
        <h3 className="text-[15px] font-semibold text-neutral-100">Delete post?</h3>
        <p className="mt-1.5 text-[13px] text-neutral-400 leading-relaxed">
          &ldquo;<span className="text-neutral-200">{stripHtml(post.title.rendered)}</span>&rdquo;
          <br />
          This will move the post to Trash on WordPress.
        </p>
        <div className="mt-5 flex gap-3 justify-end">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="px-4 py-2 rounded-lg text-[13px] font-medium text-neutral-400 hover:text-neutral-200 border border-neutral-700 hover:border-neutral-600 bg-neutral-900 transition-all"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="px-4 py-2 rounded-lg text-[13px] font-semibold text-white bg-red-600 hover:bg-red-500 disabled:opacity-60 transition-all flex items-center gap-2"
          >
            {deleting && (
              <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/>
              </svg>
            )}
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main PostsManager ──────────────────────────────────────────────────────────

export function PostsManager() {
  const [posts, setPosts] = useState<WpPost[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [page, setPage] = useState(1)
  const [statusTab, setStatusTab] = useState<string>("any")
  const [search, setSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<WpPost | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Fetch posts ──────────────────────────────────────────────────────────────

  const fetchPosts = useCallback(async (p: number, status: string, q: string) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        page: String(p),
        per_page: "20",
        status,
        search: q,
      })
      const res = await fetch(`/api/py/wp/posts?${params}`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || err.error || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setPosts(data.posts ?? [])
      setTotal(data.total ?? 0)
      setTotalPages(data.total_pages ?? 1)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load posts")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPosts(page, statusTab, search)
  }, [page, statusTab, search, fetchPosts])

  // Debounce search input
  const handleSearchInput = (val: string) => {
    setSearchInput(val)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => {
      setSearch(val)
      setPage(1)
    }, 400)
  }

  const handleTabChange = (key: string) => {
    setStatusTab(key)
    setPage(1)
  }

  // ── Delete ───────────────────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      const res = await fetch(`/api/py/wp/posts/${deleteTarget.id}`, { method: "DELETE" })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || "Delete failed")
      }
      setDeleteTarget(null)
      showToast("Post moved to trash", "success")
      fetchPosts(page, statusTab, search)
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Delete failed", "error")
    } finally {
      setDeleting(false)
    }
  }

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 4000)
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Search + tabs row */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        {/* Status tabs */}
        <div className="flex items-center gap-1 p-1 rounded-lg bg-neutral-900 border border-neutral-800">
          {STATUS_TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => handleTabChange(key)}
              className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-all ${
                statusTab === key
                  ? "bg-neutral-700 text-neutral-100"
                  : "text-neutral-500 hover:text-neutral-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative w-full sm:w-64">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-neutral-500" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="7" cy="7" r="4.5" /><path strokeLinecap="round" d="M10.5 10.5l3 3" />
          </svg>
          <input
            type="text"
            placeholder="Search posts…"
            value={searchInput}
            onChange={(e) => handleSearchInput(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-neutral-900 border border-neutral-800 text-[13px] text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-neutral-600 transition-colors"
          />
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-neutral-800 overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_140px_90px_100px_96px] gap-x-4 px-4 py-2.5 bg-neutral-900/60 border-b border-neutral-800 text-[11px] font-semibold text-neutral-500 uppercase tracking-wider">
          <span>Title</span>
          <span>Category</span>
          <span>Status</span>
          <span>Date</span>
          <span className="text-right">Actions</span>
        </div>

        {/* Loading */}
        {loading && (
          <div className="py-16 flex flex-col items-center gap-3 text-neutral-600">
            <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/>
            </svg>
            <span className="text-[13px]">Loading posts…</span>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="py-12 flex flex-col items-center gap-3 text-center px-6">
            <div className="h-8 w-8 rounded-full bg-red-500/10 flex items-center justify-center">
              <svg className="h-4 w-4 text-red-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
            </div>
            <p className="text-[13px] text-red-400">{error}</p>
            <button onClick={() => fetchPosts(page, statusTab, search)} className="text-[12px] text-neutral-500 hover:text-neutral-300 underline underline-offset-2">
              Retry
            </button>
          </div>
        )}

        {/* Empty */}
        {!loading && !error && posts.length === 0 && (
          <div className="py-16 flex flex-col items-center gap-2 text-neutral-600">
            <svg className="h-8 w-8 mb-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-[13px]">No posts found</p>
          </div>
        )}

        {/* Rows */}
        {!loading && !error && posts.map((post, idx) => (
          <div
            key={post.id}
            className={`grid grid-cols-[1fr_140px_90px_100px_96px] gap-x-4 px-4 py-3.5 items-center transition-colors hover:bg-neutral-900/40 ${
              idx < posts.length - 1 ? "border-b border-neutral-800/60" : ""
            }`}
          >
            {/* Title */}
            <div className="min-w-0">
              <p className="text-[13px] font-medium text-neutral-200 truncate leading-snug">
                {stripHtml(post.title.rendered)}
              </p>
              <p className="text-[11px] text-neutral-600 truncate mt-0.5">/{post.slug}</p>
            </div>

            {/* Category */}
            <p className="text-[12px] text-neutral-400 truncate">{getCategoryNames(post)}</p>

            {/* Status */}
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium capitalize w-fit ${STATUS_BADGE[post.status] ?? STATUS_BADGE.draft}`}>
              {post.status}
            </span>

            {/* Date */}
            <p className="text-[12px] text-neutral-500">{formatDate(post.date)}</p>

            {/* Actions */}
            <div className="flex items-center gap-1 justify-end">
              {/* Edit */}
              <Link
                href={`/dashboard/posts/${post.id}/edit`}
                title="Edit post"
                className="h-7 w-7 flex items-center justify-center rounded-md text-neutral-500 hover:text-neutral-200 hover:bg-neutral-800 transition-all"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11.5 2.5a1.414 1.414 0 012 2L5 13l-3 1 1-3 8.5-8.5z" />
                </svg>
              </Link>

              {/* View live */}
              <a
                href={post.link}
                target="_blank"
                rel="noopener noreferrer"
                title="View live"
                className="h-7 w-7 flex items-center justify-center rounded-md text-neutral-500 hover:text-neutral-200 hover:bg-neutral-800 transition-all"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 3H3a1 1 0 00-1 1v9a1 1 0 001 1h9a1 1 0 001-1v-3M10 2h4m0 0v4m0-4L6.5 9.5" />
                </svg>
              </a>

              {/* Delete */}
              <button
                onClick={() => setDeleteTarget(post)}
                title="Delete post"
                className="h-7 w-7 flex items-center justify-center rounded-md text-neutral-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2 4h12M6 4V2h4v2M5 4v9a1 1 0 001 1h4a1 1 0 001-1V4" />
                </svg>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Pagination */}
      {!loading && totalPages > 1 && (
        <div className="flex items-center justify-between text-[12px] text-neutral-500">
          <span>{total} post{total !== 1 ? "s" : ""} total</span>
          <div className="flex items-center gap-1.5">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 rounded-md border border-neutral-800 hover:border-neutral-700 hover:text-neutral-300 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              ← Prev
            </button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              const pg = i + 1
              return (
                <button
                  key={pg}
                  onClick={() => setPage(pg)}
                  className={`w-8 h-7 rounded-md border transition-all ${
                    page === pg
                      ? "border-neutral-600 bg-neutral-800 text-neutral-100"
                      : "border-neutral-800 hover:border-neutral-700 hover:text-neutral-300"
                  }`}
                >
                  {pg}
                </button>
              )
            })}
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 rounded-md border border-neutral-800 hover:border-neutral-700 hover:text-neutral-300 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <DeleteModal
          post={deleteTarget}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
          deleting={deleting}
        />
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 flex items-center gap-2.5 rounded-lg border px-4 py-3 text-[13px] font-medium shadow-xl transition-all ${
            toast.type === "success"
              ? "bg-emerald-950 border-emerald-800 text-emerald-300"
              : "bg-red-950 border-red-800 text-red-300"
          }`}
        >
          {toast.type === "success"
            ? <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
            : <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
          }
          {toast.msg}
        </div>
      )}
    </div>
  )
}
