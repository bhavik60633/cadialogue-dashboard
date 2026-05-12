// ─── Shared primitives ────────────────────────────────────────────────────────

export interface LogEntry {
  timestamp: string
  level: "info" | "warning" | "error"
  stage: string
  message: string
}

// ─── Legacy / GitHub Actions single-topic run ─────────────────────────────────

/**
 * The original PipelineRun shape written by the daily cron job.
 * Keep all fields nullable so old runs.json data stays compatible.
 */
export interface PipelineRun {
  id: string
  started_at: string
  completed_at: string | null
  status: "running" | "completed" | "failed" | "pending_approval"
  stage: string
  topic: string | null
  article_word_count: number | null
  wp_post_id: number | null
  wp_post_url: string | null
  approval_status:
    | "pending"
    | "approved"
    | "rejected"
    | "auto_approved"
    | "draft_saved"
  error: string | null
  log_entries: LogEntry[]

  // ── Dashboard-only extensions (nullable so legacy runs still parse) ──────────
  batch_id?: string | null
  topic_status?: TopicStatus | null
  topic_meta?: Topic | null
  article_sections?: ArticleSection[] | null
  images?: ImageRecord[] | null
}

// ─── Dashboard batch run types ────────────────────────────────────────────────

export type TopicStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "generating"
  | "article_ready"
  | "images_ready"
  | "publishing"
  | "published"
  | "failed"

export interface TopicSource {
  url: string
  publisher: string
}

export interface Topic {
  title: string
  summary: string
  category: string
  sources: TopicSource[]
  score: number
  keywords?: string[]
  added_by: string | null  // email of team member who manually added, null for auto
}

export interface ImageIdea {
  description: string
  style: string
  alt_text: string
  dalle_prompt: string
}

export interface GeneratedImage {
  ratio: "16:9" | "1:1" | "4:3"
  url: string   // path relative to /api/py/images/ or absolute URL
}

export interface ImageRecord {
  section_id: string
  idea_index: number
  idea: ImageIdea
  ratios: Partial<Record<"16:9" | "1:1" | "4:3", string>>  // ratio → local file path
  selected_ratio: "16:9" | "1:1" | "4:3" | null
}

export interface ArticleSection {
  id: string              // "s1", "s2", …
  heading: string | null  // h2/h3 text or null for intro
  paragraphs: string[]
  image_suggestions: ImageIdea[]
  selected_image: ImageRecord | null
}

// ─── Morning batch ─────────────────────────────────────────────────────────────

export type BatchStatus =
  | "discovering"
  | "ready_for_review"
  | "in_progress"
  | "completed"

export interface MorningBatch {
  id: string             // "batch_2026-05-07"
  date: string           // "2026-05-07"
  status: BatchStatus
  topic_run_ids: string[]
  created_at: string
}

// ─── Helper functions ─────────────────────────────────────────────────────────

export function getStatusColor(status: PipelineRun["status"]): string {
  switch (status) {
    case "completed":        return "text-green-400"
    case "failed":           return "text-red-400"
    case "running":          return "text-blue-400"
    case "pending_approval": return "text-yellow-400"
    default:                 return "text-gray-400"
  }
}

export function getApprovalColor(approval: PipelineRun["approval_status"]): string {
  switch (approval) {
    case "approved":      return "text-green-400"
    case "auto_approved": return "text-green-300"
    case "draft_saved":   return "text-yellow-400"
    case "rejected":      return "text-red-400"
    case "pending":       return "text-gray-400"
    default:              return "text-gray-400"
  }
}

export function getTopicStatusColor(status: TopicStatus): string {
  switch (status) {
    case "published":    return "text-green-400"
    case "article_ready":
    case "images_ready": return "text-blue-400"
    case "generating":
    case "publishing":   return "text-yellow-400"
    case "approved":     return "text-sky-400"
    case "rejected":     return "text-red-400"
    case "failed":       return "text-red-500"
    case "pending":      return "text-neutral-400"
    default:             return "text-gray-400"
  }
}

export function formatDuration(run: PipelineRun): string {
  if (!run.completed_at) return "Running…"
  const start = new Date(run.started_at).getTime()
  const end   = new Date(run.completed_at).getTime()
  const mins  = Math.round((end - start) / 60000)
  if (mins < 60) return `${mins}m`
  return `${Math.floor(mins / 60)}h ${mins % 60}m`
}
