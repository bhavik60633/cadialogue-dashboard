import type { PipelineRun } from "@/lib/pipeline-state"

interface Props {
  runs: PipelineRun[]
}

interface Metric {
  label: string
  value: string
  sub?: string
  accent?: string // only for semantic (success/fail)
}

export function MetricsCards({ runs }: Props) {
  const total     = runs.length
  const published = runs.filter((r) => r.status === "completed").length
  const failed    = runs.filter((r) => r.status === "failed").length
  const running   = runs.filter((r) => r.status === "running").length
  const successRate = total > 0 ? Math.round((published / total) * 100) : 0
  const lastRun   = runs[0]
  const totalWords = runs.reduce((sum, r) => sum + (r.article_word_count ?? 0), 0)

  const metrics: Metric[] = [
    {
      label: "Published",
      value: published.toString(),
      sub: `of ${total} run${total !== 1 ? "s" : ""}`,
      accent: published > 0 ? "text-emerald-400" : undefined,
    },
    {
      label: "Success Rate",
      value: `${successRate}%`,
      sub: total > 0 ? `${total} total runs` : "No runs yet",
    },
    {
      label: "Last Run",
      value: lastRun
        ? new Date(lastRun.started_at).toLocaleDateString("en-IN", {
            day: "numeric",
            month: "short",
          })
        : "—",
      sub: lastRun
        ? new Date(lastRun.started_at).toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
          })
        : "Runs daily at 7 AM",
    },
    {
      label: "Words Published",
      value:
        totalWords >= 1000
          ? `${(totalWords / 1000).toFixed(1)}k`
          : totalWords.toString(),
      sub: published > 0
        ? `~${Math.round(totalWords / Math.max(published, 1))} avg`
        : "—",
    },
    {
      label: "Failed",
      value: failed.toString(),
      sub: running > 0 ? `${running} running now` : "No active runs",
      accent: failed > 0 ? "text-red-400" : undefined,
    },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="relative rounded-xl border border-neutral-800/60 bg-neutral-900/40 p-5 overflow-hidden group hover:border-neutral-700/60 transition-colors duration-200"
        >
          {/* Subtle top-left glow on hover */}
          <div className="pointer-events-none absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            style={{ background: "radial-gradient(circle at 0% 0%, rgba(255,255,255,0.02), transparent 60%)" }}
          />

          <p className={`text-[28px] font-bold leading-none tabular-nums tracking-tight ${m.accent ?? "text-neutral-100"}`}>
            {m.value}
          </p>
          <p className="mt-2 text-[11px] font-medium uppercase tracking-widest text-neutral-500">
            {m.label}
          </p>
          {m.sub && (
            <p className="mt-1 text-[11px] text-neutral-700 truncate">{m.sub}</p>
          )}
        </div>
      ))}
    </div>
  )
}
