import { NextResponse } from "next/server"
import { readFileSync } from "fs"
import path from "path"
import type { PipelineRun } from "@/lib/pipeline-state"

export const revalidate = 30

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const filePath = path.join(process.cwd(), "pipeline", "state", "runs.json")
    const runs: PipelineRun[] = JSON.parse(readFileSync(filePath, "utf-8"))
    const run = runs.find((r) => r.id === id)
    if (!run) {
      return NextResponse.json({ error: "Run not found" }, { status: 404 })
    }
    return NextResponse.json(run)
  } catch {
    return NextResponse.json({ error: "Failed to load run" }, { status: 500 })
  }
}
