"use client";

import { useEffect, useState } from "react";

// Baked into the client bundle at build time; the browser calls the backend
// directly, so this must be a host-reachable URL, never the compose service name.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Segment = { start: number; end: number; text: string };
type Transcript = { text: string; language: string | null; duration: number | null; segments: Segment[] };
type Line = { kind: "cmd" | "out" | "err"; text: string };

const stamp = (s: number) => {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
};

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<Line[]>([{ kind: "out", text: "Choose a video, then press Generate." }]);

  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function generate() {
    if (!file) return;
    setBusy(true);
    setLines([{ kind: "cmd", text: `generate ${file.name}` }]);
    try {
      const form = new FormData();
      form.append("video", file);
      const res = await fetch(`${API}/generate`, { method: "POST", body: form });
      if (!res.ok) {
        const detail = await res.json().then((b) => b.detail, () => res.statusText);
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      const t: Transcript = await res.json();
      const header = [t.language && `language: ${t.language}`, t.duration && `duration: ${t.duration.toFixed(1)}s`]
        .filter(Boolean)
        .join("  ");
      setLines([
        { kind: "cmd", text: `generate ${file.name}` },
        ...(header ? [{ kind: "out" as const, text: header }] : []),
        ...(t.segments.length
          ? t.segments.map((s) => ({ kind: "out" as const, text: `[${stamp(s.start)}] ${s.text}` }))
          : [{ kind: "out" as const, text: t.text || "(no speech detected)" }]),
      ]);
    } catch (e) {
      setLines((l) => [...l, { kind: "err", text: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <section className="pane">
        <label className="file">
          <input type="file" accept="video/*,audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          {file ? file.name : "Choose a video"}
        </label>
        {src ? <video src={src} controls /> : <div className="empty">No video selected</div>}
        <button onClick={generate} disabled={!file || busy}>
          {busy ? "Generating…" : "Generate"}
        </button>
      </section>
      <section className="terminal" aria-live="polite">
        {lines.map((l, i) => (
          <div key={i} className={l.kind}>
            {l.kind === "cmd" ? "$ " : ""}
            {l.text}
          </div>
        ))}
        {busy && <div className="out">transcribing…</div>}
      </section>
    </main>
  );
}
