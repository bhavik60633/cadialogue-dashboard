"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import ReactMarkdown from "react-markdown"

// ─── Types ─────────────────────────────────────────────────────────────────────

interface StockPhoto {
  pexels_id: number
  description: string
  photographer: string
  thumb_url: string
  full_url: string
  width: number
  height: number
}

interface ImageIdea {
  description: string
  composition: string
  alt_text: string
  dalle_prompt: string
}

interface SectionImageState {
  // Real photos (primary)
  loadingPhotos?: boolean
  stockPhotos?: StockPhoto[]
  hasPexelsKey?: boolean
  // AI fallback
  loadingIdeas?: boolean
  aiIdeas?: ImageIdea[]
  selectedIdea?: number
  generatingAI?: boolean
  // Device upload
  uploadingDevice?: boolean
  // Result (either source)
  generatedRatios?: Record<string, string>
  selectedRatio?: "16:9" | "1:1" | "4:3"
  altText?: string
  photographer?: string
  source?: "pexels" | "ai" | "device"
  isFeatured?: boolean   // true = used as WP hero image, not embedded inline
  // UI state
  activeTab?: "photos" | "ai"
}

interface ArticleSection {
  id: string
  text: string
}

type PublishState = "idle" | "uploading" | "done" | "error"

// ─── Helpers ───────────────────────────────────────────────────────────────────

function splitSections(md: string): ArticleSection[] {
  return md.split(/(?=^#{1,2} )/m)
    .map((p, i) => ({ id: `s${i}`, text: p.trim() }))
    .filter(s => s.text.length > 0)
}

function sectionHeading(text: string) {
  const first = text.split("\n")[0]
  return first.replace(/^#{1,3}\s*/, "").slice(0, 60) || `Section`
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function ArticlePage() {
  const { id: runId } = useParams<{ id: string }>()

  const [article, setArticle]           = useState("")
  const [sections, setSections]         = useState<ArticleSection[]>([])
  type FactFlag = { severity: string; category: string; snippet: string; detail: string }
  type FactValidation = { is_clean: boolean; high_severity_count: number; flag_count: number; summary: string; flags: FactFlag[] }
  type RunMeta = {
    title: string
    wp_post_id?: number
    wp_post_url?: string
    wp_preview_url?: string
    wp_admin_url?: string
    topic_status?: string
    fact_validation?: FactValidation
  }
  const [runMeta, setRunMeta]           = useState<RunMeta | null>(null)
  const [approveState, setApproveState] = useState<"idle" | "approving" | "approved" | "rejecting" | "rejected" | "error">("idle")
  const [approveError, setApproveError] = useState("")
  const [secState, setSecState]         = useState<Record<string, SectionImageState>>({})
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState<string | null>(null)
  const [editMode, setEditMode]         = useState(false)
  const [editDraft, setEditDraft]       = useState("")
  const [savingEdit, setSavingEdit]     = useState(false)
  const [showPublish, setShowPublish]   = useState(false)
  const [publishState, setPublishState] = useState<PublishState>("idle")
  const [publishedUrl, setPublishedUrl] = useState("")
  const [publishError, setPublishError] = useState("")

  // ── Load ────────────────────────────────────────────────────────────────────

  useEffect(() => {
    fetch(`/api/py/runs/${runId}/article`)
      .then(r => { if (!r.ok) throw new Error("Not found"); return r.json() })
      .then(data => {
        const draft = data._article_draft || ""
        setArticle(draft)
        setSections(splitSections(draft))
        setRunMeta({
          title:           data.topic_meta?.title || data.topic || runId,
          wp_post_id:      data.wp_post_id,
          wp_post_url:     data.wp_post_url,
          wp_preview_url:  data.wp_preview_url,
          wp_admin_url:    data.wp_admin_url,
          topic_status:    data.topic_status,
          fact_validation: data.fact_validation,
        })
        if (data.images?.length) {
          const r: Record<string, SectionImageState> = {}
          for (const img of data.images) {
            r[img.section_id] = {
              generatedRatios: img.ratios, selectedRatio: img.selected_ratio || "16:9",
              altText: img.alt_text, photographer: img.photographer, source: img.source || "ai",
            }
          }
          setSecState(r)
        }
      })
      .catch(() => setError("Could not load article"))
      .finally(() => setLoading(false))
  }, [runId])

  // ── Edit ────────────────────────────────────────────────────────────────────

  const saveEdit = async () => {
    setSavingEdit(true)
    try {
      await fetch(`/api/py/runs/${runId}/article`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ article: editDraft }),
      })
      setArticle(editDraft); setSections(splitSections(editDraft)); setEditMode(false)
    } finally { setSavingEdit(false) }
  }

  // ── Fetch real photos ───────────────────────────────────────────────────────

  const fetchPhotos = useCallback(async (section: ArticleSection) => {
    setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingPhotos: true, stockPhotos: undefined, activeTab: "photos" } }))
    try {
      const res = await fetch(`/api/py/runs/${runId}/sections/${section.id}/stock-photos`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section_text: section.text, section_id: section.id }),
      })
      const data = await res.json()
      setSecState(p => ({
        ...p, [section.id]: {
          ...p[section.id], loadingPhotos: false,
          stockPhotos: data.photos || [], hasPexelsKey: data.has_pexels_key,
        }
      }))
    } catch {
      setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingPhotos: false } }))
    }
  }, [runId])

  // ── Use real photo ──────────────────────────────────────────────────────────

  const useStockPhoto = useCallback(async (section: ArticleSection, photo: StockPhoto) => {
    setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingPhotos: true } }))
    try {
      const res = await fetch(`/api/py/runs/${runId}/sections/${section.id}/use-stock-photo`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pexels_id: photo.pexels_id, thumb_url: photo.thumb_url, full_url: photo.full_url,
          description: photo.description, photographer: photo.photographer,
        }),
      })
      const data = await res.json()
      setSecState(p => ({
        ...p, [section.id]: {
          ...p[section.id], loadingPhotos: false,
          generatedRatios: data.ratios, selectedRatio: "16:9",
          altText: photo.description, photographer: photo.photographer,
          source: "pexels", stockPhotos: undefined,
        }
      }))
    } catch {
      setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingPhotos: false } }))
    }
  }, [runId])

  // ── AI fallback ─────────────────────────────────────────────────────────────

  const fetchAIIdeas = useCallback(async (section: ArticleSection) => {
    setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingIdeas: true, aiIdeas: undefined, activeTab: "ai" } }))
    try {
      const res = await fetch(`/api/py/runs/${runId}/sections/${section.id}/suggest-images`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section_text: section.text, section_id: section.id }),
      })
      const data = await res.json()
      setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingIdeas: false, aiIdeas: data.ideas || [] } }))
    } catch {
      setSecState(p => ({ ...p, [section.id]: { ...p[section.id], loadingIdeas: false } }))
    }
  }, [runId])

  const generateAI = useCallback(async (section: ArticleSection, idx: number) => {
    const idea = secState[section.id]?.aiIdeas?.[idx]
    if (!idea) return
    setSecState(p => ({ ...p, [section.id]: { ...p[section.id], selectedIdea: idx, generatingAI: true, generatedRatios: undefined } }))
    try {
      const res = await fetch(`/api/py/runs/${runId}/sections/${section.id}/generate-image`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea_index: idx, dalle_prompt: idea.dalle_prompt, alt_text: idea.alt_text }),
      })
      const data = await res.json()
      setSecState(p => ({
        ...p, [section.id]: {
          ...p[section.id], generatingAI: false,
          generatedRatios: data.ratios, selectedRatio: "16:9",
          altText: idea.alt_text, source: "ai",
        }
      }))
    } catch {
      setSecState(p => ({ ...p, [section.id]: { ...p[section.id], generatingAI: false } }))
    }
  }, [runId, secState])

  // ── Upload from device ───────────────────────────────────────────────────────

  const uploadDevicePhoto = useCallback(async (section: ArticleSection, file: File) => {
    setSecState(p => ({ ...p, [section.id]: { ...p[section.id], uploadingDevice: true } }))
    try {
      const form = new FormData()
      form.append("file", file)
      const res = await fetch(
        `/api/py/runs/${runId}/sections/${section.id}/upload-device-photo`,
        { method: "POST", body: form }
      )
      const data = await res.json()
      setSecState(p => ({
        ...p, [section.id]: {
          ...p[section.id], uploadingDevice: false,
          generatedRatios: data.ratios, selectedRatio: "16:9",
          altText: file.name, source: "device", stockPhotos: undefined,
        }
      }))
    } catch {
      setSecState(p => ({ ...p, [section.id]: { ...p[section.id], uploadingDevice: false } }))
    }
  }, [runId])

  // ── Toggle featured ──────────────────────────────────────────────────────────

  const toggleFeatured = useCallback((sectionId: string) => {
    setSecState(prev => {
      // Only one section can be featured at a time
      const alreadyFeatured = prev[sectionId]?.isFeatured
      const next: Record<string, SectionImageState> = {}
      for (const [k, v] of Object.entries(prev)) {
        next[k] = k === sectionId ? { ...v, isFeatured: !alreadyFeatured } : { ...v, isFeatured: false }
      }
      return next
    })
  }, [])

  // ── Select ratio ─────────────────────────────────────────────────────────────

  const selectRatio = useCallback((sectionId: string, ratio: "16:9" | "1:1" | "4:3") => {
    setSecState(p => ({ ...p, [sectionId]: { ...p[sectionId], selectedRatio: ratio } }))
    const st = secState[sectionId]
    fetch(`/api/py/runs/${runId}/select-ratio`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section_id: sectionId, idea_index: st?.selectedIdea ?? 0, ratio }),
    }).catch(() => {})
  }, [runId, secState])

  // ── Publish ──────────────────────────────────────────────────────────────────

  const publishWithImages = async () => {
    setPublishError("")
    setPublishState("uploading")
    // Pass isFeatured flags so the backend knows which section is the hero image
    const imagesWithFeatured = sections.map(s => {
      const st = secState[s.id]
      if (!st?.generatedRatios) return null
      return {
        section_id:     s.id,
        is_featured:    !!st.isFeatured,
        selected_ratio: st.selectedRatio || "16:9",
        ratios:         st.generatedRatios,
        alt_text:       st.altText || "",
        photographer:   st.photographer || "",
        source:         st.source || "ai",
      }
    }).filter(Boolean)

    try {
      const res = await fetch(`/api/py/runs/${runId}/publish-with-images`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ article, images_override: imagesWithFeatured }),
      })
      if (!res.ok) {
        let body = ""
        try {
          const j = await res.json()
          body = j.detail || j.error || JSON.stringify(j)
        } catch { body = await res.text() }
        throw new Error(`HTTP ${res.status}: ${body || "Unknown error"}`)
      }
      let attempts = 0
      while (attempts++ < 30) {
        await new Promise(r => setTimeout(r, 2000))
        const poll = await fetch(`/api/py/runs/${runId}`).then(r => r.json())
        if (poll.topic_status === "published") { setPublishedUrl(poll.wp_post_url || ""); setPublishState("done"); return }
        if (poll.topic_status === "failed") throw new Error(poll.error || "Publish failed")
      }
      throw new Error("Timed out waiting for publish to complete")
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setPublishError(msg)
      setPublishState("error")
    }
  }

  const imagesReady = Object.values(secState).filter(s => s.generatedRatios).length

  // ── Review-gate approval handlers ───────────────────────────────────────────

  async function approveDraftForPublish() {
    setApproveError("")
    setApproveState("approving")
    try {
      const res = await fetch(`/api/py/runs/${runId}/approve-for-publish`, { method: "POST" })
      if (!res.ok) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.detail || j.error || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setApproveState("approved")
      setRunMeta(m => m ? { ...m, topic_status: "published", wp_post_url: data.wp_post_url } : m)
    } catch (e) {
      setApproveError(e instanceof Error ? e.message : String(e))
      setApproveState("error")
    }
  }

  async function rejectDraft() {
    if (!confirm("Reject this article? The WordPress draft will be kept but not published.")) return
    setApproveError("")
    setApproveState("rejecting")
    try {
      const res = await fetch(`/api/py/runs/${runId}/reject-article`, { method: "POST" })
      if (!res.ok) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.detail || j.error || `HTTP ${res.status}`)
      }
      setApproveState("rejected")
      setRunMeta(m => m ? { ...m, topic_status: "rejected" } : m)
    } catch (e) {
      setApproveError(e instanceof Error ? e.message : String(e))
      setApproveState("error")
    }
  }

  const isPendingReview = runMeta?.topic_status === "pending_review"
  const isPublished     = runMeta?.topic_status === "published" || approveState === "approved"
  const isRejected      = runMeta?.topic_status === "rejected"  || approveState === "rejected"

  // ─── Render ─────────────────────────────────────────────────────────────────

  if (loading) return <Skeleton />
  if (error) return (
    <div className="max-w-3xl py-20 text-center">
      <p className="text-neutral-500 text-sm mb-4">{error}</p>
      <Link href="/dashboard/queue" className="text-xs text-red-400 hover:text-red-300">← Back to queue</Link>
    </div>
  )

  return (
    <div className="max-w-3xl pb-24 space-y-4">

      {/* Sticky header */}
      <div className="sticky top-0 z-20 -mx-6 px-6 py-3 bg-[#09090b]/90 backdrop-blur-md border-b border-neutral-800/60 flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <Link href="/dashboard/queue" className="text-[11px] text-neutral-600 hover:text-neutral-400 transition-colors">← Queue</Link>
          <h1 className="text-[14px] font-semibold text-neutral-100 truncate mt-0.5">{runMeta?.title}</h1>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!editMode ? (
            <button onClick={() => { setEditDraft(article); setEditMode(true) }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-700/60 px-3 py-1.5 text-[12px] text-neutral-400 hover:text-white hover:border-neutral-600 transition-colors">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
              </svg>
              Edit
            </button>
          ) : (
            <div className="flex gap-1.5">
              <button onClick={() => setEditMode(false)} className="px-3 py-1.5 rounded-lg text-[12px] text-neutral-500 hover:text-neutral-300">Cancel</button>
              <button onClick={saveEdit} disabled={savingEdit}
                className="px-3 py-1.5 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-[12px] text-white disabled:opacity-50">
                {savingEdit ? "Saving…" : "Save"}
              </button>
            </div>
          )}
          {!editMode && !isPendingReview && !isPublished && !isRejected && (
            <button onClick={() => setShowPublish(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 hover:bg-red-500 px-4 py-1.5 text-[12px] font-semibold text-white transition-colors">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              {imagesReady > 0 ? `Publish with ${imagesReady} photo${imagesReady > 1 ? "s" : ""}` : "Publish"}
            </button>
          )}
          {runMeta?.wp_post_url && (
            <a href={runMeta.wp_post_url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-lg border border-neutral-800 px-2.5 py-1.5 text-[11px] text-neutral-500 hover:text-white hover:border-neutral-600 transition-colors">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
              Live
            </a>
          )}
        </div>
      </div>

      {/* ── Review-gate banner (only when pending_review) ────────────────── */}
      {isPendingReview && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 space-y-3">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-amber-500/15 p-2 shrink-0">
              <svg className="h-5 w-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-semibold text-amber-300">
                Awaiting your review — not yet public
              </div>
              <div className="text-[12px] text-amber-200/70 mt-0.5">
                This article was saved as a WordPress draft. Read it below, then click <b>Approve & Go Live</b> to publish, or <b>Reject</b> to discard.
              </div>
            </div>
          </div>

          {/* Fact-validation status */}
          {runMeta?.fact_validation && (
            <div className={`rounded-lg p-3 text-[12px] ${
              runMeta.fact_validation.is_clean
                ? "bg-emerald-500/5 border border-emerald-500/20 text-emerald-300"
                : "bg-red-500/5 border border-red-500/30 text-red-300"
            }`}>
              <div className="flex items-center gap-2 font-medium mb-1">
                {runMeta.fact_validation.is_clean ? "✓" : "⚠"} Fact-validator: {runMeta.fact_validation.summary}
              </div>
              {runMeta.fact_validation.flags.length > 0 && (
                <ul className="mt-2 space-y-1.5 text-[11px] opacity-90">
                  {runMeta.fact_validation.flags.slice(0, 6).map((f, i) => (
                    <li key={i} className="leading-relaxed">
                      <span className={`inline-block px-1.5 py-0.5 rounded mr-2 text-[10px] font-semibold uppercase ${
                        f.severity === "high" ? "bg-red-500/30 text-red-100" : "bg-amber-500/20 text-amber-100"
                      }`}>{f.severity}</span>
                      <span className="font-mono">{f.detail}</span>
                      <div className="text-neutral-400 mt-0.5 italic">…{f.snippet}…</div>
                    </li>
                  ))}
                  {runMeta.fact_validation.flags.length > 6 &&
                    <li className="opacity-70">+ {runMeta.fact_validation.flags.length - 6} more</li>}
                </ul>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2 pt-1">
            {runMeta?.wp_preview_url && (
              <a href={runMeta.wp_preview_url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-700 bg-neutral-900/60 px-3 py-2 text-[12px] text-neutral-200 hover:bg-neutral-800 hover:border-neutral-600 transition-colors">
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Preview live rendering
              </a>
            )}
            {runMeta?.wp_admin_url && (
              <a href={runMeta.wp_admin_url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-700 bg-neutral-900/60 px-3 py-2 text-[12px] text-neutral-200 hover:bg-neutral-800 hover:border-neutral-600 transition-colors">
                Edit in WP Admin
              </a>
            )}
            <div className="flex-1" />
            <button onClick={rejectDraft}
              disabled={approveState === "approving" || approveState === "rejecting"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-[12px] font-semibold text-red-300 hover:bg-red-500/20 hover:text-red-200 transition-colors disabled:opacity-40">
              {approveState === "rejecting" ? "Rejecting…" : "Reject"}
            </button>
            <button onClick={approveDraftForPublish}
              disabled={approveState === "approving" || approveState === "rejecting" || (runMeta?.fact_validation && !runMeta.fact_validation.is_clean)}
              title={runMeta?.fact_validation && !runMeta.fact_validation.is_clean
                ? "Resolve high-severity fact flags first (edit the article to remove or fix them)"
                : "Promote the WordPress draft to public"}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 px-4 py-2 text-[12px] font-semibold text-white transition-colors disabled:bg-neutral-700 disabled:text-neutral-400 disabled:cursor-not-allowed">
              {approveState === "approving" ? "Publishing…" : "✓ Approve & Go Live"}
            </button>
          </div>

          {approveError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {approveError}
            </div>
          )}
        </div>
      )}

      {isPublished && approveState === "approved" && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4 flex items-center gap-3">
          <span className="text-emerald-400 text-lg">✓</span>
          <div className="flex-1">
            <div className="text-[13px] font-semibold text-emerald-300">Live on cadialogue.in</div>
            {runMeta?.wp_post_url && (
              <a href={runMeta.wp_post_url} target="_blank" rel="noopener noreferrer"
                className="text-[12px] text-emerald-200/80 hover:text-emerald-100 underline underline-offset-2">
                {runMeta.wp_post_url}
              </a>
            )}
          </div>
        </div>
      )}

      {isRejected && (
        <div className="rounded-xl border border-neutral-700 bg-neutral-900/40 p-4 text-[12px] text-neutral-400">
          Rejected. The WordPress draft is preserved at <a className="text-neutral-300 underline" href={runMeta?.wp_admin_url || "#"} target="_blank" rel="noopener noreferrer">WP Admin</a> in case you want to recover any content.
        </div>
      )}

      {/* Edit mode */}
      {editMode && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-1">
          <textarea value={editDraft} onChange={e => setEditDraft(e.target.value)} rows={30}
            className="w-full rounded-lg bg-neutral-900 text-neutral-300 font-mono text-[12px] leading-relaxed p-4 focus:outline-none resize-y"
            spellCheck={false} />
        </div>
      )}

      {/* Sections */}
      {!editMode && sections.map(section => (
        <SectionCard
          key={section.id}
          section={section}
          state={secState[section.id] || {}}
          onFetchPhotos={() => fetchPhotos(section)}
          onUsePhoto={photo => useStockPhoto(section, photo)}
          onFetchAI={() => fetchAIIdeas(section)}
          onGenerateAI={idx => generateAI(section, idx)}
          onSelectRatio={r => selectRatio(section.id, r)}
          onRetry={() => fetchPhotos(section)}
          onUploadDevice={file => uploadDevicePhoto(section, file)}
          onToggleFeatured={() => toggleFeatured(section.id)}
        />
      ))}

      {/* Publish modal */}
      {showPublish && (
        <PublishModal
          sections={sections} secState={secState}
          publishState={publishState} publishedUrl={publishedUrl}
          publishError={publishError}
          onConfirm={publishWithImages}
          onClose={() => { setShowPublish(false); setPublishState("idle"); setPublishError("") }}
        />
      )}
    </div>
  )
}

// ─── Section card ──────────────────────────────────────────────────────────────

function SectionCard({
  section, state, onFetchPhotos, onUsePhoto, onFetchAI, onGenerateAI,
  onSelectRatio, onRetry, onUploadDevice, onToggleFeatured,
}: {
  section: ArticleSection
  state: SectionImageState
  onFetchPhotos: () => void
  onUsePhoto: (p: StockPhoto) => void
  onFetchAI: () => void
  onGenerateAI: (idx: number) => void
  onSelectRatio: (r: "16:9" | "1:1" | "4:3") => void
  onRetry: () => void
  onUploadDevice: (f: File) => void
  onToggleFeatured: () => void
}) {
  const fileRef   = useRef<HTMLInputElement>(null)
  const hasImage  = !!state.generatedRatios
  const activeUrl = state.generatedRatios?.[state.selectedRatio || "16:9"]
  const loading   = state.loadingPhotos || state.loadingIdeas || state.generatingAI || state.uploadingDevice

  return (
    <div className={`rounded-xl border overflow-hidden transition-colors ${
      hasImage ? "border-neutral-700/60 bg-neutral-900/40" : "border-neutral-800/50 bg-neutral-900/30"
    }`}>

      {/* Article text */}
      <div className="px-5 pt-5 pb-3 prose prose-invert prose-sm max-w-none
        prose-headings:font-semibold prose-headings:text-neutral-100
        prose-h1:text-[17px] prose-h2:text-[15px] prose-h3:text-[13px]
        prose-p:text-[13px] prose-p:text-neutral-400 prose-p:leading-[1.7]
        prose-strong:text-neutral-300 prose-li:text-neutral-400 prose-li:text-[13px]">
        <ReactMarkdown>{section.text}</ReactMarkdown>
      </div>

      {/* Placed image preview */}
      {hasImage && activeUrl && (
        <div className="mx-5 mb-3 rounded-lg overflow-hidden border border-neutral-700/40">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={activeUrl} alt={state.altText || ""}
            className="w-full object-cover"
            style={{ aspectRatio: state.selectedRatio === "1:1" ? "1/1" : state.selectedRatio === "4:3" ? "4/3" : "16/9" }} />
          <div className="flex items-center gap-1 px-3 py-2 bg-neutral-900/80 border-t border-neutral-800/60">
            {(["16:9", "1:1", "4:3"] as const).map(r => (
              <button key={r} onClick={() => onSelectRatio(r)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  state.selectedRatio === r ? "bg-neutral-700 text-white" : "text-neutral-600 hover:text-neutral-300"
                }`}>{r}</button>
            ))}
            <span className="flex-1" />
            {state.source === "pexels" && state.photographer && (
              <span className="text-[9px] text-neutral-700">📷 {state.photographer} / Pexels</span>
            )}
            {/* Hero image toggle */}
            <button
              onClick={onToggleFeatured}
              title={state.isFeatured ? "Currently set as hero/featured image (won't embed inline)" : "Set as hero image (appears at top of article)"}
              className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                state.isFeatured
                  ? "border-amber-500/50 bg-amber-500/10 text-amber-400"
                  : "border-neutral-800 text-neutral-700 hover:text-neutral-400"
              }`}
            >
              {state.isFeatured ? "★ Hero" : "☆ Hero"}
            </button>
            <span className="text-[10px] text-emerald-500 flex items-center gap-1">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              Ready
            </span>
            <button onClick={onRetry} className="text-[10px] text-neutral-600 hover:text-neutral-400">↺ Replace</button>
          </div>
        </div>
      )}

      {/* Image panel footer */}
      <div className="border-t border-neutral-800/40 px-5 py-3">

        {/* Initial state — no image, nothing loading */}
        {!hasImage && !loading && !state.stockPhotos && !state.aiIdeas && (
          <div className="flex flex-col gap-1.5 w-full">
            {/* Hidden file input */}
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) onUploadDevice(f); e.target.value = "" }}
            />
            <div className="flex gap-1.5">
              <button onClick={onFetchPhotos}
                className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg border border-dashed border-neutral-700/60 px-3 py-2.5 text-[12px] text-neutral-500 hover:text-neutral-200 hover:border-neutral-600 transition-all">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M2.25 21h19.5M4.5 16.5h.008v.008H4.5V16.5z" />
                </svg>
                Find real photos
              </button>
              <button onClick={() => fileRef.current?.click()}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-neutral-700/60 px-3 py-2.5 text-[12px] text-neutral-500 hover:text-neutral-200 hover:border-neutral-600 transition-all">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                </svg>
                Upload from device
              </button>
            </div>
          </div>
        )}

        {/* Has image — allow replace */}
        {hasImage && !state.stockPhotos && !state.aiIdeas && !loading && (
          <div className="flex items-center gap-3">
            <button onClick={onRetry} className="text-[11px] text-neutral-700 hover:text-neutral-500 transition-colors">
              ↺ Replace with photo
            </button>
            <span className="text-neutral-800 text-[11px]">·</span>
            <button onClick={() => fileRef.current?.click()} className="text-[11px] text-neutral-700 hover:text-neutral-500 transition-colors">
              ↑ Upload from device
            </button>
          </div>
        )}

        {/* Loading spinner */}
        {loading && (
          <div className="flex items-center gap-2 text-[12px] text-neutral-500 py-1">
            <span className="h-3.5 w-3.5 rounded-full border-2 border-neutral-700 border-t-neutral-300 animate-spin" />
            {state.loadingPhotos   && "Searching real photos…"}
            {state.loadingIdeas    && "Thinking of image concepts…"}
            {state.generatingAI    && "Generating AI image (~20 sec)…"}
            {state.uploadingDevice && "Processing uploaded photo…"}
          </div>
        )}

        {/* No Pexels key warning */}
        {state.hasPexelsKey === false && !loading && (
          <NoPexelsKey onUseAI={onFetchAI} />
        )}

        {/* Stock photo grid */}
        {state.stockPhotos && state.stockPhotos.length > 0 && !loading && (
          <PhotoGrid
            photos={state.stockPhotos}
            onSelect={onUsePhoto}
            onRefresh={onRetry}
            onUseAI={onFetchAI}
          />
        )}

        {/* Empty search result */}
        {state.stockPhotos && state.stockPhotos.length === 0 && !loading && (
          <div className="text-center py-3">
            <p className="text-[12px] text-neutral-500 mb-2">No matching photos found</p>
            <div className="flex gap-2 justify-center">
              <button onClick={onRetry} className="text-[11px] text-neutral-500 hover:text-neutral-300">Try again</button>
              <span className="text-neutral-700">·</span>
              <button onClick={onFetchAI} className="text-[11px] text-neutral-500 hover:text-neutral-300">Use AI instead</button>
            </div>
          </div>
        )}

        {/* AI ideas picker (fallback tab) */}
        {state.aiIdeas && !loading && (
          <AIIdeaPicker
            ideas={state.aiIdeas}
            selectedIdx={state.selectedIdea}
            generating={state.generatingAI}
            onGenerate={onGenerateAI}
            onBackToPhotos={onRetry}
          />
        )}
      </div>
    </div>
  )
}

// ─── Photo grid (Pexels) ────────────────────────────────────────────────────────

function PhotoGrid({
  photos, onSelect, onRefresh, onUseAI,
}: {
  photos: StockPhoto[]
  onSelect: (p: StockPhoto) => void
  onRefresh: () => void
  onUseAI: () => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-neutral-600">
          Real photos — click to use
        </p>
        <div className="flex items-center gap-3">
          <button onClick={onRefresh} className="text-[10px] text-neutral-600 hover:text-neutral-400">↺ Refresh</button>
          <button onClick={onUseAI} className="text-[10px] text-neutral-600 hover:text-neutral-400">🎨 Generate AI instead</button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-1.5">
        {photos.map(photo => (
          <button
            key={photo.pexels_id}
            onClick={() => onSelect(photo)}
            className="group relative rounded-lg overflow-hidden border border-neutral-800/60 hover:border-neutral-600 transition-all aspect-video bg-neutral-900"
            title={photo.description}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={photo.thumb_url}
              alt={photo.description}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            />
            {/* Hover overlay */}
            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
              <svg className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
            </div>
            {/* Photographer credit */}
            <div className="absolute bottom-0 left-0 right-0 px-1.5 py-1 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
              <p className="text-[8px] text-white/70 truncate">{photo.photographer}</p>
            </div>
          </button>
        ))}
      </div>

      <p className="text-[9px] text-neutral-700">Photos from Pexels — free for commercial use</p>
    </div>
  )
}

// ─── No Pexels key ──────────────────────────────────────────────────────────────

function NoPexelsKey({ onUseAI }: { onUseAI: () => void }) {
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 space-y-2">
      <p className="text-[12px] text-amber-400 font-medium">Add a free Pexels API key for real photos</p>
      <p className="text-[11px] text-neutral-500">
        Get a free key at{" "}
        <a href="https://www.pexels.com/api/" target="_blank" rel="noopener noreferrer"
          className="text-amber-400/80 hover:text-amber-300 underline">pexels.com/api</a>
        {" "}(free, no credit card), then add <code className="text-amber-400/70 text-[10px]">PEXELS_API_KEY=...</code> to your <code className="text-amber-400/70 text-[10px]">.env</code> file.
      </p>
      <button onClick={onUseAI}
        className="text-[11px] text-neutral-400 hover:text-white border border-neutral-700 rounded px-3 py-1 transition-colors">
        Use AI generation instead →
      </button>
    </div>
  )
}

// ─── AI idea picker (fallback) ─────────────────────────────────────────────────

function AIIdeaPicker({
  ideas, selectedIdx, generating, onGenerate, onBackToPhotos,
}: {
  ideas: ImageIdea[]
  selectedIdx?: number
  generating?: boolean
  onGenerate: (idx: number) => void
  onBackToPhotos: () => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-1">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-neutral-600">AI Generate</p>
        <button onClick={onBackToPhotos} className="text-[10px] text-neutral-600 hover:text-neutral-400">← Real photos</button>
      </div>
      <div className="space-y-1.5">
        {ideas.map((idea, idx) => (
          <button key={idx} onClick={() => !generating && onGenerate(idx)} disabled={generating}
            className={`group w-full text-left rounded-lg border px-3 py-2.5 transition-all
              ${selectedIdx === idx && generating ? "border-amber-500/40 bg-amber-500/5"
                : "border-neutral-800/50 bg-neutral-900/30 hover:border-neutral-700 hover:bg-neutral-800/40"}
              ${generating ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}>
            <div className="flex items-center gap-2.5">
              <span className="text-[12px] shrink-0">📷</span>
              <div className="flex-1 min-w-0">
                <p className="text-[12px] text-neutral-300 font-medium leading-snug">{idea.description}</p>
                <p className="text-[10px] text-neutral-600 mt-0.5 capitalize">{idea.composition}</p>
              </div>
              {generating && selectedIdx === idx
                ? <span className="h-3.5 w-3.5 rounded-full border-2 border-amber-600 border-t-amber-300 animate-spin" />
                : <svg className="h-3.5 w-3.5 text-neutral-700 group-hover:text-neutral-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z" />
                  </svg>
              }
            </div>
          </button>
        ))}
      </div>
      {generating && (
        <p className="text-[11px] text-amber-500/80 flex items-center gap-1.5 pt-1">
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500/60 animate-pulse" />
          Generating with gpt-image-1 — ~20 seconds…
        </p>
      )}
    </div>
  )
}

// ─── Publish modal ──────────────────────────────────────────────────────────────

function PublishModal({
  sections, secState, publishState, publishedUrl, publishError, onConfirm, onClose,
}: {
  sections: ArticleSection[]
  secState: Record<string, SectionImageState>
  publishState: PublishState
  publishedUrl: string
  publishError: string
  onConfirm: () => void
  onClose: () => void
}) {
  const withImages = sections.filter(s => secState[s.id]?.generatedRatios)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-neutral-800 bg-neutral-950 shadow-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-neutral-800 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-neutral-100">
            {publishState === "done" ? "✓ Published!" : "Publish to WordPress"}
          </h2>
          <button onClick={onClose} className="text-neutral-600 hover:text-neutral-300">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {publishState === "idle" && (
            <>
              <p className="text-[12px] text-neutral-500">
                Images will be uploaded to WordPress media library and embedded in the article.
              </p>
              {withImages.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-neutral-600">Photos to embed</p>
                  {withImages.map(s => {
                    const st = secState[s.id]
                    const url = st?.generatedRatios?.[st?.selectedRatio || "16:9"]
                    return (
                      <div key={s.id} className="flex items-center gap-3 rounded-lg bg-neutral-900/60 px-3 py-2">
                        {url && <img src={url} alt="" className="h-10 w-16 rounded object-cover shrink-0" />}
                        <div className="min-w-0 flex-1">
                          <p className="text-[11px] text-neutral-400 truncate">{sectionHeading(s.text)}</p>
                          <p className="text-[10px] text-neutral-600">
                            {st?.source === "pexels" ? `📷 ${st.photographer} / Pexels` : st?.source === "device" ? "📁 Device upload" : "🎨 AI generated"}
                            {" · "}{st?.selectedRatio}
                            {st?.isFeatured && <span className="ml-1 text-amber-500">★ hero</span>}
                          </p>
                        </div>
                        <svg className="h-3.5 w-3.5 text-emerald-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                        </svg>
                      </div>
                    )
                  })}
                </div>
              )}
              {withImages.length === 0 && (
                <p className="text-[12px] text-amber-400/80">No photos selected yet. The article will publish text-only.</p>
              )}
            </>
          )}

          {publishState === "uploading" && (
            <div className="py-6 flex flex-col items-center gap-3 text-center">
              <span className="h-8 w-8 rounded-full border-2 border-neutral-700 border-t-red-500 animate-spin" />
              <p className="text-[13px] text-neutral-400">Uploading photos to WordPress…</p>
              <p className="text-[11px] text-neutral-600">20–40 seconds</p>
            </div>
          )}

          {publishState === "done" && (
            <div className="py-4 flex flex-col items-center gap-3 text-center">
              <div className="h-12 w-12 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
                <svg className="h-6 w-6 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-semibold text-neutral-100 mb-1">Article updated</p>
                <p className="text-[12px] text-neutral-500">Photos are live on WordPress</p>
              </div>
              {publishedUrl && (
                <a href={publishedUrl} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 px-4 py-2 text-[12px] text-white transition-colors">
                  View article →
                </a>
              )}
            </div>
          )}

          {publishState === "error" && (
            <div className="space-y-2">
              <p className="text-[12px] font-semibold text-red-400">Publish failed</p>
              {publishError ? (
                <pre className="text-[11px] text-red-300/90 bg-red-950/30 border border-red-900/40 rounded-md p-3 whitespace-pre-wrap break-words max-h-40 overflow-auto">
                  {publishError}
                </pre>
              ) : (
                <p className="text-[12px] text-red-400">Unknown error. Check the terminal for FastAPI logs.</p>
              )}
            </div>
          )}
        </div>

        {(publishState === "idle" || publishState === "error") && (
          <div className="px-6 py-4 border-t border-neutral-800 flex justify-end gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded-lg text-[12px] text-neutral-500 hover:text-neutral-300">Cancel</button>
            <button onClick={onConfirm}
              className="px-5 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-[12px] font-semibold text-white transition-colors">
              {publishState === "error" ? "Retry" : "Confirm & Publish →"}
            </button>
          </div>
        )}
        {publishState === "done" && (
          <div className="px-6 py-4 border-t border-neutral-800 flex justify-end">
            <button onClick={onClose} className="px-4 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-[12px] text-white">Done</button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Skeleton ───────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="max-w-3xl space-y-4 animate-pulse">
      <div className="h-8 w-2/3 rounded-lg bg-neutral-800" />
      {[1, 2, 3].map(i => (
        <div key={i} className="rounded-xl border border-neutral-800/50 p-5 space-y-2">
          <div className="h-4 w-1/3 rounded bg-neutral-800" />
          <div className="h-3 w-full rounded bg-neutral-800/60" />
          <div className="h-3 w-5/6 rounded bg-neutral-800/60" />
        </div>
      ))}
    </div>
  )
}
