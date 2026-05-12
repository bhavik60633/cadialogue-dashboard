/**
 * Serve generated images from pipeline/state/images/ directory.
 * Path: /api/images/{run_id}/{filename}
 */
import { NextRequest, NextResponse } from "next/server"
import { readFileSync } from "fs"
import path from "path"

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path: segments } = await params
  const filePath = path.join(
    process.cwd(),
    "pipeline",
    "state",
    "images",
    ...segments
  )

  try {
    const data = readFileSync(filePath)
    return new NextResponse(data, {
      headers: {
        "Content-Type": "image/png",
        "Cache-Control": "public, max-age=86400, immutable",
      },
    })
  } catch {
    return NextResponse.json({ error: "Image not found" }, { status: 404 })
  }
}
