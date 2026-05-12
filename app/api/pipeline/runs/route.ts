import { NextResponse } from "next/server"
import { readFileSync } from "fs"
import path from "path"
import type { PipelineRun } from "@/lib/pipeline-state"

export const revalidate = 60   // Revalidate every 60 seconds

export async function GET() {
  try {
    const filePath = path.join(process.cwd(), "pipeline", "state", "runs.json")
    const raw = readFileSync(filePath, "utf-8")
    const runs: PipelineRun[] = JSON.parse(raw)
    return NextResponse.json(runs)
  } catch {
    return NextResponse.json([], { status: 200 })
  }
}
