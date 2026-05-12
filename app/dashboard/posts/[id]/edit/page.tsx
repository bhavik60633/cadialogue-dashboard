"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { PostEditor, type PostData } from "@/components/posts/PostEditor"

export default function EditPostPage() {
  const params = useParams<{ id: string }>()
  const postId = Number(params.id)

  const [postData, setPostData] = useState<PostData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!postId) return
    fetch(`/api/py/wp/posts/${postId}`)
      .then(async (r) => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          throw new Error(err.detail || err.error || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then((wp) => {
        // Map WP REST API shape → PostData
        setPostData({
          id: wp.id,
          title: wp.title?.rendered ?? "",
          slug: wp.slug ?? "",
          content: wp.content?.rendered ?? "",
          excerpt: wp.excerpt?.rendered ?? "",
          status: wp.status ?? "draft",
          categories: wp.categories ?? [],
          link: wp.link ?? "",
        })
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [postId])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24 text-neutral-600">
        <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"/>
        </svg>
        <span className="text-[13px]">Loading post…</span>
      </div>
    )
  }

  if (error || !postData) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24 text-center px-6">
        <div className="h-10 w-10 rounded-full bg-red-500/10 flex items-center justify-center">
          <svg className="h-5 w-5 text-red-400" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
          </svg>
        </div>
        <p className="text-[14px] text-red-400">{error ?? "Post not found"}</p>
      </div>
    )
  }

  return <PostEditor initialData={postData} mode="edit" />
}
