import Link from "next/link"
import type { PipelineRun } from "@/lib/pipeline-state"
import { formatDuration } from "@/lib/pipeline-state"
import { RunStatusBadge } from "./RunStatusBadge"

interface Props {
  runs: PipelineRun[]
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center rounded-xl border border-dashed border-neutral-800/60">
      {/* Icon */}
      <div className="mb-5 rounded-full border border-neutral-800 bg-neutral-900/60 p-5">
        <svg
          className="h-8 w-8 text-neutral-700"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.25}
        >
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
          />
        </svg>
      </div>
      <p className="text-sm font-medium text-neutral-400">No pipeline runs yet</p>
      <p className="mt-1.5 max-w-xs text-[12px] text-neutral-600 leading-relaxed">
        The automated pipeline runs daily at 7:00 AM IST via GitHub Actions.
        Runs will appear here after the first execution.
      </p>
      <Link
        href="/dashboard/queue"
        className="mt-5 inline-flex items-center gap-1.5 rounded-md bg-neutral-800 px-3.5 py-2 text-[12px] font-medium text-neutral-300 hover:bg-neutral-700 hover:text-white transition-colors"
      >
        Go to Today's Queue →
      </Link>
    </div>
  )
}

export function RunsTable({ runs }: Props) {
  if (runs.length === 0) return <EmptyState />

  return (
    <div className="rounded-xl border border-neutral-800/60 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-800/60 bg-neutral-900/30">
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-widest text-neutral-600">
              Date
            </th>
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-widest text-neutral-600">
              Topic
            </th>
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-widest text-neutral-600">
              Status
            </th>
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-widest text-neutral-600 hidden sm:table-cell">
              Words
            </th>
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-widest text-neutral-600 hidden md:table-cell">
              Duration
            </th>
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-widest text-neutral-600">
              Article
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run, i) => (
            <tr
              key={run.id}
              className={`
                group border-b border-neutral-800/40 hover:bg-neutral-900/40 transition-colors duration-100
                ${i === runs.length - 1 ? "border-b-0" : ""}
              `}
            >
              {/* Date */}
              <td className="px-5 py-3.5 whitespace-nowrap">
                <Link
                  href={`/dashboard/runs/${run.id}`}
                  className="text-[12px] text-neutral-500 hover:text-neutral-300 transition-colors"
                >
                  {new Date(run.started_at).toLocaleDateString("en-IN", {
                    day: "numeric",
                    month: "short",
                    year: "2-digit",
                  })}
                  <span className="ml-1.5 text-neutral-700 font-mono text-[10px]">
                    {new Date(run.started_at).toLocaleTimeString("en-IN", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </Link>
              </td>

              {/* Topic */}
              <td className="px-5 py-3.5 max-w-[280px]">
                <Link
                  href={`/dashboard/runs/${run.id}`}
                  className="block text-[13px] text-neutral-200 hover:text-white transition-colors leading-snug line-clamp-2 group-hover:text-white"
                >
                  {run.topic ?? (
                    <span className="text-neutral-600 italic text-[12px]">
                      Researching…
                    </span>
                  )}
                </Link>
              </td>

              {/* Status */}
              <td className="px-5 py-3.5 whitespace-nowrap">
                <RunStatusBadge status={run.status} />
              </td>

              {/* Words */}
              <td className="px-5 py-3.5 hidden sm:table-cell">
                <span className="text-[12px] text-neutral-500 tabular-nums font-mono">
                  {run.article_word_count
                    ? run.article_word_count.toLocaleString()
                    : <span className="text-neutral-700">—</span>
                  }
                </span>
              </td>

              {/* Duration */}
              <td className="px-5 py-3.5 hidden md:table-cell">
                <span className="text-[11px] text-neutral-600 tabular-nums font-mono">
                  {formatDuration(run)}
                </span>
              </td>

              {/* Article link */}
              <td className="px-5 py-3.5">
                {run.wp_post_url ? (
                  <a
                    href={run.wp_post_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[12px] text-neutral-500 hover:text-neutral-200 transition-colors"
                  >
                    View
                    <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={1.5}>
                      <path d="M2.5 2.5h7m0 0v7m0-7L2.5 9.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </a>
                ) : (
                  <span className="text-neutral-700 text-[12px]">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
