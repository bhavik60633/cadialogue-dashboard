import type { PipelineRun } from "@/lib/pipeline-state"

type Status = PipelineRun["status"]

const CONFIG: Record<Status, { label: string; dot: string; text: string; bg: string }> = {
  completed:        { label: "Published",         dot: "bg-emerald-500",   text: "text-emerald-400", bg: "bg-emerald-500/8 border-emerald-500/20"  },
  failed:           { label: "Failed",            dot: "bg-red-500",       text: "text-red-400",     bg: "bg-red-500/8 border-red-500/20"           },
  running:          { label: "Running",           dot: "bg-sky-400",       text: "text-sky-400",     bg: "bg-sky-500/8 border-sky-500/20"           },
  pending_approval: { label: "Pending Approval",  dot: "bg-amber-400",     text: "text-amber-400",   bg: "bg-amber-500/8 border-amber-500/20"       },
}

export function RunStatusBadge({ status }: { status: Status }) {
  const cfg = CONFIG[status] ?? {
    label: status,
    dot: "bg-neutral-500",
    text: "text-neutral-400",
    bg: "bg-neutral-800/60 border-neutral-700/40",
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-medium border ${cfg.bg} ${cfg.text}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full shrink-0 ${cfg.dot} ${status === "running" ? "animate-pulse" : ""}`}
      />
      {cfg.label}
    </span>
  )
}
