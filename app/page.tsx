import { VercelV0Chat } from "@/components/ui/v0-ai-chat";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-black p-8">
      <VercelV0Chat />
    </main>
  );
}
