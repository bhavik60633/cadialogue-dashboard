import Link from "next/link"
import { notFound } from "next/navigation"
import { readFileSync } from "fs"
import path from "path"
import type { PipelineRun, LogEntry } from "@/lib/pipeline-state"
import {
  getStatusColor,
  getApprovalColor,
  formatDuration,
} from "@/lib/pipeline-state"
import { RunStatusBadge } from "@/components/dashboard/RunStatusBadge"

async function getRun(id: string): Promise<PipelineRun | null> {
  try {
    const filePath = path.join(process.cwd(), "pipeline", "state", "runs.json")
    const runs: PipelineRun[] = JSON.parse(readFileSync(filePath, "utf-8"))
    return runs.find((r) => r.id === id) ?? null
  } catch {
    return null
  }
}

const LOG_LEVEL_COLORS: Record<LogEntry["level"], string> = {
  info:    "text-neutral-400",
  warning: "text-yellow-400",
  error:   "text-red-400",
}

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const run = await getRun(id)
  if (!run) notFound()

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <Link href="/dashboard" className="text-sm text-neutral-500 hover:text-white transition-colors">
          ← Back to runs
        </Link>
      </div>

      {/* Header */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 mb-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h1 className="text-xl font-bold text-white mb-1">
              {run.topic ?? "Run " + run.id}
            </h1>
            <p className="text-sm text-neutral-500">
              {new Date(run.started_at).toLocaleString("en-IN", {
                dateStyle: "full", timeStyle: "short",
              })}
            </p>
          </div>
          <RunStatusBadge status={run.status} />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-neutral-500 text-xs mb-1">Duration</div>
            <div className="text-neutral-200">{formatDuration(run)}</div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs mb-1">Word count</div>
            <div className="text-neutral-200">{run.article_word_count ?? "—"}</div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs mb-1">Approval</div>
            <div className={getApprovalColor(run.approval_status)}>
              {run.approval_status.replace("_", " ")}
            </div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs mb-1">Stage reached</div>
            <div className="text-neutral-200">{run.stage}</div>
          </div>
        </div>

        {run.wp_post_url && (
          <div className="mt-4 pt-4 border-t border-neutral-800">
            <a
              href={run.wp_post_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-400 hover:text-sky-300 text-sm transition-colors"
            >
              View published article →
            </a>
          </div>
        )}

        {run.error && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
            <div className="text-red-400 text-xs font-mono">{run.error}</div>
          </div>
        )}
      </div>

      {/* Log entries */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6">
        <h2 className="text-sm font-semibold text-neutral-300 mb-4">Pipeline Log</h2>
        <div className="space-y-1 font-mono text-xs">
          {run.log_entries.length === 0 ? (
            <p className="text-neutral-600">No log entries</p>
          ) : (
            run.log_entries.map((entry, i) => (
              <div key={i} className="flex gap-3">
                <span className="text-neutral-600 shrink-0">
                  {new Date(entry.timestamp).toLocaleTimeString("en-IN", {
                    hour: "2-digit", minute: "2-digit", second: "2-digit",
                  })}
                </span>
                <span className="text-neutral-600 w-16 shrink-0">[{entry.stage}]</span>
                <span className={LOG_LEVEL_COLORS[entry.level]}>
                  {entry.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
