"use client"

import {
  useCallback, useEffect, useRef, useState,
} from "react"
import { useRouter } from "next/navigation"

// ── Types ──────────────────────────────────────────────────────────────────────

type BlockType = "paragraph" | "heading" | "image" | "list"

interface ParagraphBlock { id: string; type: "paragraph"; content: string }
interface HeadingBlock   { id: string; type: "heading"; level: 2 | 3; content: string }
interface ImageBlock     { id: string; type: "image"; url: string; alt: string; previewUrl?: string; uploading?: boolean; uploadError?: string; mediaId?: number }
interface ListBlock      { id: string; type: "list"; content: string }
type Block = ParagraphBlock | HeadingBlock | ImageBlock | ListBlock

export interface PostData {
  id?: number
  title: string
  slug: string
  content: string    // HTML
  excerpt: string
  status: "publish" | "draft" | "private"
  categories: number[]
  link?: string
}

interface WpCategory { id: number; name: string; slug: string }

interface Props {
  initialData?: PostData
  mode: "new" | "edit"
}

// ── Helpers ────────────────────────────────────────────────────────────────────

const uid = () => Math.random().toString(36).slice(2, 9)

function titleToSlug(t: string) {
  return t.toLowerCase().trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
}

function stripHtmlTags(html: string) {
  return html.replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&#8217;/g, "'").replace(/&#8220;/g, '"').replace(/&#8221;/g, '"')
    .trim()
}

/** Basic inline markdown → HTML for paragraphs */
function inlineToHTML(text: string) {
  return text
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
}

/** Convert block list → WordPress-compatible HTML */
function blocksToHTML(blocks: Block[]): string {
  return blocks.map((b) => {
    if (b.type === "paragraph") {
      const text = b.content.trim()
      if (!text) return ""
      // Multi-line: split on double newlines → multiple <p>
      return text.split(/\n\n+/).map(para =>
        para.trim() ? `<p>${inlineToHTML(para.replace(/\n/g, "<br/>"))}</p>` : ""
      ).filter(Boolean).join("\n\n")
    }
    if (b.type === "heading") {
      const text = b.content.trim()
      if (!text) return ""
      return `<h${b.level}>${text}</h${b.level}>`
    }
    if (b.type === "image") {
      if (!b.url) return ""
      return (
        `<figure class="wp-block-image size-large">` +
        `<img src="${b.url}" alt="${b.alt.replace(/"/g, "&quot;")}" ` +
        `style="width:100%;aspect-ratio:16/9;object-fit:cover;" />` +
        `</figure>`
      )
    }
    if (b.type === "list") {
      const lines = b.content.split("\n").map((l) => l.replace(/^[-*]\s*/, "").trim()).filter(Boolean)
      if (!lines.length) return ""
      return `<ul>\n${lines.map((l) => `<li>${inlineToHTML(l)}</li>`).join("\n")}\n</ul>`
    }
    return ""
  }).filter(Boolean).join("\n\n")
}

/** Parse WordPress HTML back into blocks (runs client-side only) */
function htmlToBlocks(html: string): Block[] {
  if (typeof document === "undefined") return [{ id: uid(), type: "paragraph", content: "" }]
  const parser = new DOMParser()
  const doc = parser.parseFromString(html, "text/html")
  const blocks: Block[] = []

  for (const el of Array.from(doc.body.children)) {
    const tag = el.tagName.toLowerCase()
    if (tag === "p") {
      const text = el.textContent?.trim() ?? ""
      if (text) blocks.push({ id: uid(), type: "paragraph", content: text })
    } else if (tag === "h2") {
      const text = el.textContent?.trim() ?? ""
      if (text) blocks.push({ id: uid(), type: "heading", level: 2, content: text })
    } else if (tag === "h3") {
      const text = el.textContent?.trim() ?? ""
      if (text) blocks.push({ id: uid(), type: "heading", level: 3, content: text })
    } else if (tag === "ul" || tag === "ol") {
      const items = Array.from(el.querySelectorAll("li"))
        .map((li) => `- ${li.textContent?.trim() ?? ""}`)
        .filter((l) => l.length > 2)
      if (items.length) blocks.push({ id: uid(), type: "list", content: items.join("\n") })
    } else if (tag === "figure") {
      const img = el.querySelector("img")
      if (img?.src) blocks.push({ id: uid(), type: "image", url: img.src, alt: img.alt || "" })
    } else if (tag === "div") {
      // Some WP blocks are wrapped in divs — try to extract text
      const text = el.textContent?.trim() ?? ""
      if (text && text.length > 10) blocks.push({ id: uid(), type: "paragraph", content: text })
    }
  }

  return blocks.length > 0 ? blocks : [{ id: uid(), type: "paragraph", content: "" }]
}

// ── Auto-growing textarea ──────────────────────────────────────────────────────

function AutoTextarea({
  value, onChange, placeholder, className, autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  autoFocus?: boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!ref.current) return
    ref.current.style.height = "auto"
    ref.current.style.height = `${ref.current.scrollHeight}px`
  }, [value])

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      autoFocus={autoFocus}
      rows={1}
      className={`w-full resize-none overflow-hidden bg-transparent focus:outline-none ${className ?? ""}`}
    />
  )
}

// ── Block type picker popup ────────────────────────────────────────────────────

const BLOCK_TYPES: { type: BlockType; label: string; icon: React.ReactNode }[] = [
  {
    type: "paragraph",
    label: "Paragraph",
    icon: (
      <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" d="M2 4h12M2 7h8M2 10h10M2 13h6" />
      </svg>
    ),
  },
  {
    type: "heading",
    label: "Heading",
    icon: (
      <span className="text-[11px] font-bold leading-none">H2</span>
    ),
  },
  {
    type: "image",
    label: "Image",
    icon: (
      <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <rect x="1" y="3" width="14" height="10" rx="1.5" />
        <circle cx="5.5" cy="6.5" r="1" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M1 11l3.5-3.5L7 10l2.5-2.5L15 12" />
      </svg>
    ),
  },
  {
    type: "list",
    label: "Bullet List",
    icon: (
      <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <circle cx="2.5" cy="4" r="1" fill="currentColor" stroke="none"/>
        <circle cx="2.5" cy="8" r="1" fill="currentColor" stroke="none"/>
        <circle cx="2.5" cy="12" r="1" fill="currentColor" stroke="none"/>
        <path strokeLinecap="round" d="M5 4h9M5 8h9M5 12h9" />
      </svg>
    ),
  },
]

/** Thin divider with always-visible "+" between blocks */
function AddBlockButton({ onAdd }: { onAdd: (type: BlockType) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  return (
    <div ref={ref} className="relative flex items-center justify-center py-1">
      {/* Divider line */}
      <div className="absolute inset-x-0 top-1/2 -translate-y-px h-px bg-neutral-800" />
      {/* Always-visible "+" button */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative z-10 h-6 w-6 rounded-full border border-neutral-700 bg-neutral-900 flex items-center justify-center text-neutral-500 hover:text-neutral-200 hover:border-neutral-500 hover:bg-neutral-800 transition-all"
        title="Add block"
      >
        <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" d="M6 2v8M2 6h8" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-20 top-8 left-1/2 -translate-x-1/2 flex gap-1 p-1.5 rounded-xl border border-neutral-700 bg-[#111113] shadow-2xl">
          {BLOCK_TYPES.map(({ type, label, icon }) => (
            <button
              key={type}
              type="button"
              onClick={() => { onAdd(type); setOpen(false) }}
              className="flex flex-col items-center gap-1.5 px-4 py-2.5 rounded-lg text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 transition-all min-w-[60px]"
            >
              {icon}
              <span className="text-[11px] whitespace-nowrap">{label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Prominent bottom toolbar — always visible, one click per block type */
function BottomAddBar({ onAdd }: { onAdd: (type: BlockType) => void }) {
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {BLOCK_TYPES.map(({ type, label, icon }) => (
        <button
          key={type}
          type="button"
          onClick={() => onAdd(type)}
          className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg border text-[13px] font-medium transition-all ${
            type === "image"
              ? "border-red-800/60 bg-red-950/20 text-red-400 hover:bg-red-900/30 hover:border-red-700"
              : "border-neutral-800 bg-neutral-900/60 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700 hover:bg-neutral-800/60"
          }`}
        >
          {icon}
          {type === "image" ? "Add Image" : `Add ${label}`}
        </button>
      ))}
    </div>
  )
}

// ── Individual block renderers ─────────────────────────────────────────────────

function BlockShell({
  children, onRemove, onMoveUp, onMoveDown, isFirst, isLast,
}: {
  children: React.ReactNode
  onRemove: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  isFirst: boolean
  isLast: boolean
}) {
  return (
    <div className="group relative rounded-lg border border-transparent hover:border-neutral-800 bg-transparent hover:bg-neutral-900/30 px-3 py-2 transition-all">
      {children}
      {/* Action row */}
      <div className="absolute right-2 top-2 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          type="button" onClick={onMoveUp} disabled={isFirst}
          className="h-5 w-5 rounded flex items-center justify-center text-neutral-600 hover:text-neutral-300 hover:bg-neutral-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          title="Move up"
        >
          <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M2 8l4-4 4 4"/></svg>
        </button>
        <button
          type="button" onClick={onMoveDown} disabled={isLast}
          className="h-5 w-5 rounded flex items-center justify-center text-neutral-600 hover:text-neutral-300 hover:bg-neutral-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          title="Move down"
        >
          <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M2 4l4 4 4-4"/></svg>
        </button>
        <button
          type="button" onClick={onRemove}
          className="h-5 w-5 rounded flex items-center justify-center text-neutral-600 hover:text-red-400 hover:bg-red-500/10 transition-all"
          title="Remove block"
        >
          <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M2 2l8 8M10 2L2 10"/></svg>
        </button>
      </div>
    </div>
  )
}

function ParagraphBlockEditor({ block, onChange }: { block: ParagraphBlock; onChange: (content: string) => void }) {
  return (
    <AutoTextarea
      value={block.content}
      onChange={onChange}
      placeholder="Write your paragraph… (**bold**, *italic*, [link](url))"
      className="text-[14px] text-neutral-200 leading-relaxed placeholder-neutral-700 pr-16 min-h-[60px]"
      autoFocus={block.content === ""}
    />
  )
}

function HeadingBlockEditor({ block, onChange, onLevelChange }: {
  block: HeadingBlock
  onChange: (content: string) => void
  onLevelChange: (level: 2 | 3) => void
}) {
  return (
    <div className="flex items-start gap-2">
      <select
        value={block.level}
        onChange={(e) => onLevelChange(Number(e.target.value) as 2 | 3)}
        className="mt-1 shrink-0 h-7 rounded-md border border-neutral-700 bg-neutral-900 text-[11px] font-bold text-neutral-400 focus:outline-none focus:border-neutral-500 px-2 cursor-pointer"
      >
        <option value={2}>H2</option>
        <option value={3}>H3</option>
      </select>
      <input
        type="text"
        value={block.content}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Section heading…"
        autoFocus={block.content === ""}
        className={`flex-1 bg-transparent focus:outline-none text-neutral-100 font-semibold placeholder-neutral-700 pr-16 ${
          block.level === 2 ? "text-[18px]" : "text-[16px]"
        }`}
      />
    </div>
  )
}

interface PexelsPhoto {
  pexels_id: number
  description: string
  photographer: string
  thumb_url: string
  full_url: string
}

function ImageBlockEditor({
  block,
  onAltChange,
  onUpload,
  onRemoveImage,
  onSetUrl,
}: {
  block: ImageBlock
  onAltChange: (alt: string) => void
  onUpload: (file: File) => void
  onRemoveImage: () => void
  onSetUrl: (url: string, alt: string) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<"upload" | "search">("upload")
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<PexelsPhoto[]>([])
  const [searching, setSearching] = useState(false)
  const [searchErr, setSearchErr] = useState<string | null>(null)
  const [adopting, setAdopting] = useState<number | null>(null) // pexels_id being adopted

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file?.type.startsWith("image/")) onUpload(file)
  }

  const handleSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    setSearchErr(null)
    setResults([])
    try {
      const res = await fetch(`/api/py/wp/search-photos?q=${encodeURIComponent(query)}&per_page=12`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || err.error || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setResults(data.photos ?? [])
      if (!data.photos?.length) setSearchErr("No photos found — try different keywords")
    } catch (err: unknown) {
      setSearchErr(err instanceof Error ? err.message : "Search failed")
    } finally {
      setSearching(false)
    }
  }

  const handlePickPhoto = async (photo: PexelsPhoto) => {
    setAdopting(photo.pexels_id)
    try {
      const res = await fetch("/api/py/wp/use-pexels-photo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_url: photo.full_url,
          description: photo.description,
          photographer: photo.photographer,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || err.error || "Failed to use photo")
      }
      const data = await res.json()
      onSetUrl(data.source_url, data.alt || photo.description)
    } catch (err: unknown) {
      setSearchErr(err instanceof Error ? err.message : "Failed to add photo")
    } finally {
      setAdopting(null)
    }
  }

  // If image already chosen, just show preview + alt text
  if (block.url && !block.uploading) {
    return (
      <div className="rounded-lg border border-neutral-800 overflow-hidden pr-16">
        <div className="relative bg-neutral-950">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={block.previewUrl || block.url}
            alt={block.alt || "image"}
            className="w-full object-cover max-h-56"
          />
          <button
            type="button"
            onClick={onRemoveImage}
            className="absolute top-2 right-2 h-6 w-6 rounded-full bg-black/60 flex items-center justify-center text-neutral-300 hover:text-white hover:bg-black transition-all"
            title="Remove image"
          >
            <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M2 2l8 8M10 2L2 10"/></svg>
          </button>
        </div>
        <div className="px-3 py-2 bg-neutral-900/60 border-t border-neutral-800">
          <input
            type="text"
            value={block.alt}
            onChange={(e) => onAltChange(e.target.value)}
            placeholder="Alt text (describe the image for accessibility + SEO)"
            className="w-full bg-transparent text-[12px] text-neutral-400 placeholder-neutral-700 focus:outline-none focus:text-neutral-200 transition-colors"
          />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 pr-16">
      {/* Uploading spinner */}
      {block.uploading && (
        <div className="flex items-center gap-3 rounded-lg border border-neutral-700 bg-neutral-900/40 p-4">
          <svg className="h-5 w-5 animate-spin text-red-400" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/>
          </svg>
          <span className="text-[13px] text-neutral-400">Uploading to WordPress…</span>
        </div>
      )}

      {/* Upload error */}
      {block.uploadError && (
        <div className="flex items-center gap-2 rounded-lg border border-red-800 bg-red-950/30 px-3 py-2">
          <svg className="h-4 w-4 text-red-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
          </svg>
          <span className="text-[12px] text-red-300">{block.uploadError}</span>
          <button type="button" onClick={() => fileRef.current?.click()} className="ml-auto text-[12px] text-red-400 hover:text-red-200 underline">Retry</button>
        </div>
      )}

      {!block.uploading && (
        <>
          {/* Tab bar */}
          <div className="flex rounded-lg border border-neutral-800 overflow-hidden text-[12px] font-medium w-fit">
            <button
              type="button"
              onClick={() => setTab("upload")}
              className={`flex items-center gap-1.5 px-3 py-1.5 transition-all ${tab === "upload" ? "bg-neutral-700 text-neutral-100" : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"}`}
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 10V3M5 6l3-3 3 3M2 12v1a1 1 0 001 1h10a1 1 0 001-1v-1" />
              </svg>
              Upload from device
            </button>
            <button
              type="button"
              onClick={() => setTab("search")}
              className={`flex items-center gap-1.5 px-3 py-1.5 transition-all border-l border-neutral-800 ${tab === "search" ? "bg-neutral-700 text-neutral-100" : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"}`}
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.8}>
                <circle cx="7" cy="7" r="4.5"/><path strokeLinecap="round" d="M10.5 10.5l3 3"/>
              </svg>
              Search Pexels photos
            </button>
          </div>

          {/* Upload tab */}
          {tab === "upload" && (
            <div
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              onClick={() => fileRef.current?.click()}
              className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-neutral-700 hover:border-neutral-500 bg-neutral-900/40 cursor-pointer py-8 transition-colors"
            >
              <svg className="h-8 w-8 text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <p className="text-[13px] text-neutral-500">Click to upload or drag & drop</p>
              <p className="text-[11px] text-neutral-700">PNG, JPG, WEBP up to 10MB</p>
            </div>
          )}

          {/* Search tab */}
          {tab === "search" && (
            <div className="space-y-3">
              {/* Search bar */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                  placeholder="e.g. Indian stock market, RBI headquarters, gold coins…"
                  className="flex-1 px-3 py-2 rounded-lg border border-neutral-700 bg-neutral-900 text-[13px] text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-neutral-500 transition-colors"
                />
                <button
                  type="button"
                  onClick={handleSearch}
                  disabled={searching || !query.trim()}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-50 text-[13px] font-medium text-white transition-all flex items-center gap-2 shrink-0"
                >
                  {searching
                    ? <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/></svg>
                    : <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2}><circle cx="7" cy="7" r="4.5"/><path strokeLinecap="round" d="M10.5 10.5l3 3"/></svg>
                  }
                  {searching ? "Searching…" : "Search"}
                </button>
              </div>

              {/* Error */}
              {searchErr && (
                <p className="text-[12px] text-red-400">{searchErr}</p>
              )}

              {/* Results grid */}
              {results.length > 0 && (
                <div className="grid grid-cols-3 gap-2">
                  {results.map((photo) => (
                    <button
                      key={photo.pexels_id}
                      type="button"
                      onClick={() => handlePickPhoto(photo)}
                      disabled={adopting !== null}
                      className="group relative rounded-lg overflow-hidden border border-neutral-800 hover:border-neutral-600 transition-all aspect-video bg-neutral-900 disabled:opacity-60"
                      title={photo.description}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={photo.thumb_url}
                        alt={photo.description}
                        className="w-full h-full object-cover"
                      />
                      {/* Hover overlay */}
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all flex items-center justify-center">
                        {adopting === photo.pexels_id ? (
                          <svg className="h-5 w-5 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/>
                          </svg>
                        ) : (
                          <span className="opacity-0 group-hover:opacity-100 text-white text-[11px] font-semibold bg-black/60 px-2 py-1 rounded-md transition-all">
                            Use photo
                          </span>
                        )}
                      </div>
                      {/* Photographer */}
                      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-1.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <p className="text-[9px] text-neutral-300 truncate">📷 {photo.photographer}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}

              {results.length > 0 && (
                <p className="text-[10px] text-neutral-700 text-right">
                  Photos from <a href="https://www.pexels.com" target="_blank" rel="noopener noreferrer" className="underline hover:text-neutral-500">Pexels</a> — free to use
                </p>
              )}
            </div>
          )}
        </>
      )}

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onUpload(file)
          e.target.value = ""
        }}
      />
    </div>
  )
}

function ListBlockEditor({ block, onChange }: { block: ListBlock; onChange: (content: string) => void }) {
  return (
    <AutoTextarea
      value={block.content}
      onChange={onChange}
      placeholder={"- First item\n- Second item\n- Third item"}
      className="text-[14px] text-neutral-200 leading-relaxed placeholder-neutral-700 pr-16 min-h-[80px] font-mono"
    />
  )
}

// ── Main PostEditor component ──────────────────────────────────────────────────

export function PostEditor({ initialData, mode }: Props) {
  const router = useRouter()

  // Form state
  const [title, setTitle] = useState(initialData?.title ? stripHtmlTags(initialData.title) : "")
  const [slug, setSlug] = useState(initialData?.slug ?? "")
  const [slugManual, setSlugManual] = useState(mode === "edit")
  const [categoryId, setCategoryId] = useState<number>(initialData?.categories?.[0] ?? 0)
  const [postStatus, setPostStatus] = useState<"publish" | "draft">(
    initialData?.status === "publish" ? "publish" : "draft"
  )
  const [excerpt, setExcerpt] = useState(
    initialData?.excerpt ? stripHtmlTags(initialData.excerpt) : ""
  )
  const [blocks, setBlocks] = useState<Block[]>([
    { id: uid(), type: "paragraph", content: "" },
  ])
  const [categories, setCategories] = useState<WpCategory[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error"; url?: string } | null>(null)
  const [liveUrl, setLiveUrl] = useState(initialData?.link ?? "")
  const [showExcerpt, setShowExcerpt] = useState(false)

  // Parse HTML into blocks on mount (client-only)
  useEffect(() => {
    if (initialData?.content) {
      const parsed = htmlToBlocks(initialData.content)
      if (parsed.length > 0) setBlocks(parsed)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fetch WP categories
  useEffect(() => {
    fetch("/api/py/wp/categories")
      .then((r) => r.json())
      .then((d) => setCategories(d.categories ?? []))
      .catch(() => {})
  }, [])

  // Auto-slug from title (new post only, unless manually edited)
  useEffect(() => {
    if (!slugManual) setSlug(titleToSlug(title))
  }, [title, slugManual])

  // ── Block operations ─────────────────────────────────────────────────────────

  const addBlockAfter = useCallback((afterId: string, type: BlockType) => {
    setBlocks((prev) => {
      const idx = prev.findIndex((b) => b.id === afterId)
      const newBlock: Block =
        type === "paragraph" ? { id: uid(), type: "paragraph", content: "" }
        : type === "heading"   ? { id: uid(), type: "heading", level: 2, content: "" }
        : type === "image"     ? { id: uid(), type: "image", url: "", alt: "" }
        : { id: uid(), type: "list", content: "" }
      const next = [...prev]
      next.splice(idx + 1, 0, newBlock)
      return next
    })
  }, [])

  const updateBlock = useCallback((id: string, updates: Partial<Block>) => {
    setBlocks((prev) => prev.map((b) => b.id === id ? { ...b, ...updates } as Block : b))
  }, [])

  const removeBlock = useCallback((id: string) => {
    setBlocks((prev) => {
      if (prev.length <= 1) return [{ id: uid(), type: "paragraph", content: "" }]
      return prev.filter((b) => b.id !== id)
    })
  }, [])

  const moveBlock = useCallback((id: string, dir: "up" | "down") => {
    setBlocks((prev) => {
      const idx = prev.findIndex((b) => b.id === id)
      if (dir === "up" && idx === 0) return prev
      if (dir === "down" && idx === prev.length - 1) return prev
      const next = [...prev]
      const target = dir === "up" ? idx - 1 : idx + 1
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }, [])

  // ── Image upload ─────────────────────────────────────────────────────────────

  const uploadImage = useCallback(async (blockId: string, file: File) => {
    // Show local preview immediately
    const previewUrl = URL.createObjectURL(file)
    updateBlock(blockId, { uploading: true, previewUrl, url: "", uploadError: undefined } as Partial<ImageBlock>)

    try {
      const form = new FormData()
      form.append("file", file)
      form.append("alt_text", file.name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " "))
      form.append("title", file.name.replace(/\.[^.]+$/, ""))

      const res = await fetch("/api/py/wp/media", { method: "POST", body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || err.error || "Upload failed")
      }
      const media = await res.json()
      updateBlock(blockId, {
        url: media.source_url,
        previewUrl,
        mediaId: media.id,
        uploading: false,
        uploadError: undefined,
      } as Partial<ImageBlock>)
    } catch (err: unknown) {
      updateBlock(blockId, {
        uploading: false,
        uploadError: err instanceof Error ? err.message : "Upload failed",
      } as Partial<ImageBlock>)
    }
  }, [updateBlock])

  // ── Save / Publish ────────────────────────────────────────────────────────────

  const handleSave = async (targetStatus: "publish" | "draft") => {
    if (!title.trim()) {
      setSaveError("Please add a title before saving.")
      return
    }
    setSaving(true)
    setSaveError(null)

    const html = blocksToHTML(blocks)
    const payload: Record<string, unknown> = {
      title: title.trim(),
      content: html,
      status: targetStatus,
      ...(slug.trim() ? { slug: slug.trim() } : {}),
      ...(excerpt.trim() ? { excerpt: excerpt.trim() } : {}),
      ...(categoryId ? { categories: [categoryId] } : {}),
    }

    try {
      const isNew = mode === "new"
      const url = isNew
        ? "/api/py/wp/posts"
        : `/api/py/wp/posts/${initialData!.id}`
      const method = isNew ? "POST" : "PUT"

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || err.error || `HTTP ${res.status}`)
      }

      const post = await res.json()
      const postUrl: string = post.link ?? ""
      setLiveUrl(postUrl)
      setPostStatus(targetStatus)
      setSlug(post.slug ?? slug)
      setSlugManual(true)

      const action = isNew ? "created" : "updated"
      const statusLabel = targetStatus === "publish" ? "Published" : "Saved as draft"
      showToast(`${statusLabel} ✓`, "success", postUrl)

      if (isNew && post.id) {
        // Redirect to edit page so the URL is stable
        router.replace(`/dashboard/posts/${post.id}/edit`)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Save failed"
      setSaveError(msg)
      showToast(msg, "error")
    } finally {
      setSaving(false)
    }
  }

  const showToast = (msg: string, type: "success" | "error", url?: string) => {
    setToast({ msg, type, url })
    setTimeout(() => setToast(null), 5000)
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-32">
      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-[13px] text-neutral-500">
          <button
            type="button"
            onClick={() => router.push("/dashboard/posts")}
            className="hover:text-neutral-300 transition-colors flex items-center gap-1"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 12l-4-4 4-4" />
            </svg>
            Posts
          </button>
          <span>/</span>
          <span className="text-neutral-300">{mode === "new" ? "New Post" : "Edit Post"}</span>
        </div>
        {liveUrl && (
          <a
            href={liveUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[12px] text-neutral-500 hover:text-neutral-200 transition-colors"
          >
            View live
            <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 2H10M10 2v6M10 2L2 10" />
            </svg>
          </a>
        )}
      </div>

      {/* ── Title ── */}
      <div>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Post title…"
          className="w-full bg-transparent text-[28px] font-bold text-neutral-100 placeholder-neutral-700 focus:outline-none leading-tight"
        />
        {/* Slug */}
        <div className="mt-2 flex items-center gap-1.5 text-[12px] text-neutral-600">
          <span>cadialogue.in/</span>
          <input
            type="text"
            value={slug}
            onChange={(e) => { setSlug(e.target.value); setSlugManual(true) }}
            className="bg-transparent text-neutral-500 hover:text-neutral-300 focus:text-neutral-200 focus:outline-none border-b border-transparent focus:border-neutral-700 transition-all min-w-[120px] max-w-xs"
            placeholder="post-slug"
          />
        </div>
      </div>

      {/* ── Meta row ── */}
      <div className="flex flex-wrap gap-3 pb-4 border-b border-neutral-800">
        {/* Category */}
        <div className="flex flex-col gap-1">
          <label className="text-[11px] text-neutral-600 uppercase tracking-wider font-semibold">Category</label>
          <select
            value={categoryId}
            onChange={(e) => setCategoryId(Number(e.target.value))}
            className="h-8 rounded-md border border-neutral-700 bg-neutral-900 text-[13px] text-neutral-300 px-2.5 focus:outline-none focus:border-neutral-500 cursor-pointer"
          >
            <option value={0}>Uncategorized</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        {/* Status */}
        <div className="flex flex-col gap-1">
          <label className="text-[11px] text-neutral-600 uppercase tracking-wider font-semibold">Status</label>
          <div className="flex rounded-md border border-neutral-700 overflow-hidden text-[12px] font-medium">
            {(["draft", "publish"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setPostStatus(s)}
                className={`px-3 h-8 transition-all capitalize ${
                  postStatus === s
                    ? s === "publish"
                      ? "bg-emerald-600 text-white"
                      : "bg-neutral-700 text-neutral-100"
                    : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"
                }`}
              >
                {s === "publish" ? "Publish" : "Draft"}
              </button>
            ))}
          </div>
        </div>

        {/* Excerpt toggle */}
        <div className="flex flex-col gap-1">
          <label className="text-[11px] text-neutral-600 uppercase tracking-wider font-semibold">Excerpt</label>
          <button
            type="button"
            onClick={() => setShowExcerpt((v) => !v)}
            className={`h-8 px-3 rounded-md border border-neutral-700 text-[12px] font-medium transition-all ${
              showExcerpt ? "bg-neutral-700 text-neutral-200" : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"
            }`}
          >
            {showExcerpt ? "Hide" : "Add excerpt"}
          </button>
        </div>
      </div>

      {/* ── Excerpt ── */}
      {showExcerpt && (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/30 px-4 py-3">
          <label className="text-[11px] text-neutral-600 uppercase tracking-wider font-semibold block mb-2">Excerpt</label>
          <AutoTextarea
            value={excerpt}
            onChange={setExcerpt}
            placeholder="Short description shown in search results and social cards…"
            className="text-[13px] text-neutral-300 leading-relaxed placeholder-neutral-700"
          />
        </div>
      )}

      {/* ── Content blocks ── */}
      <div className="space-y-1">
        <p className="text-[11px] text-neutral-600 uppercase tracking-wider font-semibold mb-3">Content</p>

        {blocks.map((block, idx) => (
          <div key={block.id}>
            <BlockShell
              onRemove={() => removeBlock(block.id)}
              onMoveUp={() => moveBlock(block.id, "up")}
              onMoveDown={() => moveBlock(block.id, "down")}
              isFirst={idx === 0}
              isLast={idx === blocks.length - 1}
            >
              {block.type === "paragraph" && (
                <ParagraphBlockEditor
                  block={block}
                  onChange={(content) => updateBlock(block.id, { content })}
                />
              )}
              {block.type === "heading" && (
                <HeadingBlockEditor
                  block={block}
                  onChange={(content) => updateBlock(block.id, { content })}
                  onLevelChange={(level) => updateBlock(block.id, { level })}
                />
              )}
              {block.type === "image" && (
                <ImageBlockEditor
                  block={block}
                  onAltChange={(alt) => updateBlock(block.id, { alt })}
                  onUpload={(file) => uploadImage(block.id, file)}
                  onRemoveImage={() => updateBlock(block.id, { url: "", previewUrl: undefined, mediaId: undefined, uploadError: undefined })}
                  onSetUrl={(url, alt) => updateBlock(block.id, { url, alt, previewUrl: undefined, uploading: false, uploadError: undefined })}
                />
              )}
              {block.type === "list" && (
                <ListBlockEditor
                  block={block}
                  onChange={(content) => updateBlock(block.id, { content })}
                />
              )}
            </BlockShell>

            {/* Add block button between blocks */}
            <AddBlockButton onAdd={(type) => addBlockAfter(block.id, type)} />
          </div>
        ))}

        {/* ── Always-visible add toolbar at the bottom ── */}
        <BottomAddBar onAdd={(type) => addBlockAfter(blocks[blocks.length - 1].id, type)} />
      </div>

      {/* ── Error ── */}
      {saveError && (
        <div className="rounded-lg border border-red-800 bg-red-950/30 px-4 py-3 text-[13px] text-red-300">
          {saveError}
        </div>
      )}

      {/* ── Sticky save bar ── */}
      <div className="fixed bottom-0 left-0 right-0 z-30 border-t border-neutral-800 bg-[#09090b]/90 backdrop-blur-md px-6 py-3">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-4">
          <div className="text-[12px] text-neutral-600">
            {blocks.filter((b) => b.type === "paragraph" || b.type === "heading").length} block{blocks.length !== 1 ? "s" : ""}
            {" · "}
            {blocks.filter((b) => b.type === "image" && b.url).length} image{blocks.filter((b) => b.type === "image" && (b as ImageBlock).url).length !== 1 ? "s" : ""}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleSave("draft")}
              disabled={saving}
              className="h-8 px-4 rounded-lg border border-neutral-700 bg-neutral-900 text-[13px] font-medium text-neutral-400 hover:text-neutral-200 hover:border-neutral-600 disabled:opacity-50 transition-all"
            >
              Save Draft
            </button>
            <button
              type="button"
              onClick={() => handleSave("publish")}
              disabled={saving}
              className="h-8 px-5 rounded-lg bg-red-600 hover:bg-red-500 text-[13px] font-semibold text-white disabled:opacity-50 transition-all flex items-center gap-2"
            >
              {saving && (
                <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/>
                </svg>
              )}
              {saving ? "Saving…" : postStatus === "publish" ? "Update Post" : "Publish Post"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Toast ── */}
      {toast && (
        <div
          className={`fixed bottom-20 right-6 z-50 flex items-center gap-3 rounded-xl border px-4 py-3 text-[13px] font-medium shadow-2xl transition-all ${
            toast.type === "success"
              ? "bg-emerald-950 border-emerald-800 text-emerald-300"
              : "bg-red-950 border-red-800 text-red-300"
          }`}
        >
          {toast.type === "success"
            ? <svg className="h-4 w-4 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
            : <svg className="h-4 w-4 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
          }
          <span>{toast.msg}</span>
          {toast.url && (
            <a
              href={toast.url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:opacity-80"
            >
              View →
            </a>
          )}
        </div>
      )}
    </div>
  )
}
