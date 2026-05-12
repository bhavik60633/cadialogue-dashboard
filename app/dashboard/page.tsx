import Link from "next/link"
import { MetricsCards } from "@/components/dashboard/MetricsCards"
import { RunsTable } from "@/components/dashboard/RunsTable"
import type { PipelineRun } from "@/lib/pipeline-state"

async function getRuns(): Promise<PipelineRun[]> {
  try {
    const { readFileSync } = await import("fs")
    const path = await import("path")
    const filePath = path.default.join(process.cwd(), "pipeline", "state", "runs.json")
    return JSON.parse(readFileSync(filePath, "utf-8")) as PipelineRun[]
  } catch {
    return []
  }
}

export default async function DashboardPage() {
  const runs = await getRuns()
  const recentRuns = runs.slice(0, 25)

  return (
    <div className="space-y-8">
      {/* ── Page header ── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-neutral-100 tracking-tight">
            Pipeline Overview
          </h1>
          <p className="mt-1 text-[13px] text-neutral-500">
            Finance content automation — runs daily at 7:00 AM IST via GitHub Actions
          </p>
        </div>

        <Link
          href="/dashboard/queue"
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-red-600 hover:bg-red-500 px-4 py-2 text-[13px] font-medium text-white transition-colors"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 3v10M3 8l5 5 5-5" />
          </svg>
          Today's Queue
        </Link>
      </div>

      {/* ── Metrics ── */}
      <MetricsCards runs={runs} />

      {/* ── Recent runs ── */}
      <div>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-[14px] font-semibold text-neutral-200">Recent Runs</h2>
            <p className="mt-0.5 text-[11px] text-neutral-600">
              {runs.length > 0
                ? `${runs.length} total run${runs.length !== 1 ? "s" : ""} · showing last ${recentRuns.length}`
                : "No runs recorded yet"}
            </p>
          </div>
        </div>

        <RunsTable runs={recentRuns} />
      </div>
    </div>
  )
}
