"use client";

import { useCallback, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

const LANGUAGES = [
  "Spanish", "French", "German", "Japanese", "Korean",
  "Chinese", "Burmese", "Thai", "Hindi", "Arabic", "Portuguese",
];

type Status = "idle" | "uploading" | "working" | "done" | "cancelled" | "failed";

type UploadInfo = {
  video_path: string;
  filename: string;
  size_mb: number;
  duration: number;
  has_audio: boolean;
};

type Translation = { language: string; text: string; srt: string };

function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function downloadText(filename: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");

  const [wantTranscript, setWantTranscript] = useState(true);
  const [wantAnalysis, setWantAnalysis] = useState(false);
  const [targets, setTargets] = useState<string[]>([]);
  const [query, setQuery] = useState("");

  const [transcript, setTranscript] = useState("");
  const [detectedLanguage, setDetectedLanguage] = useState("");
  const [translations, setTranslations] = useState<Translation[]>([]);
  const [summary, setSummary] = useState("");
  // A stage that ran and produced nothing still deserves a tab: without this we
  // cannot tell "no analysis requested" from "analysed, found nothing to say".
  const [transcribed, setTranscribed] = useState(false);
  const [analyzed, setAnalyzed] = useState(false);
  const [activeTab, setActiveTab] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const busy = status === "uploading" || status === "working";

  const reset = () => {
    setTranscript("");
    setTranslations([]);
    setSummary("");
    setTranscribed(false);
    setAnalyzed(false);
    setDetectedLanguage("");
    setError("");
    setStage("");
  };

  const handleFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0];
    if (!chosen) return;
    setFile(chosen);
    setUpload(null);
    setStatus("idle");
    reset();
  };

  const toggleTarget = (language: string) => {
    setTargets((current) =>
      current.includes(language)
        ? current.filter((item) => item !== language)
        : [...current, language],
    );
  };

  const run = useCallback(async () => {
    if (!file) return;

    abortRef.current = new AbortController();
    const { signal } = abortRef.current;
    reset();
    setStatus("uploading");

    try {
      let media = upload;

      // Skip re-uploading if this file is already on the server.
      if (!media) {
        const form = new FormData();
        form.append("file", file);
        const response = await fetch(`${API_BASE}/upload`, {
          method: "POST",
          body: form,
          signal,
        });
        if (!response.ok) {
          throw new Error((await response.json()).detail ?? "Upload failed");
        }
        media = (await response.json()) as UploadInfo;
        setUpload(media);
      }

      setStatus("working");
      setStage("starting");

      const response = await fetch(`${API_BASE}/process/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_path: media.video_path,
          transcribe: wantTranscript || targets.length > 0,
          analyze: wantAnalysis,
          translate_to: targets,
          query: query.trim() || null,
        }),
        signal,
      });
      if (!response.ok || !response.body) {
        throw new Error("The server rejected the request");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      // SSE frames can straddle a network read, so hold a buffer and only
      // consume complete `\n\n`-terminated frames.
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") continue;

          const event = JSON.parse(payload);
          switch (event.event) {
            case "status":
              setStage(event.language ? `translating → ${event.language}` : event.stage);
              break;
            case "transcript":
              setTranscript(event.text);
              setDetectedLanguage(event.language ?? "");
              setTranscribed(true);
              if (event.text) setActiveTab("transcript");
              break;
            case "translation":
              setTranslations((current) => [
                ...current,
                { language: event.language, text: event.text, srt: event.srt },
              ]);
              break;
            case "analysis":
              setSummary(event.summary);
              setAnalyzed(true);
              break;
            case "error":
              throw new Error(event.detail);
          }
        }
      }

      setStage("");
      setStatus("done");
    } catch (caught: unknown) {
      if (caught instanceof Error && caught.name === "AbortError") {
        setStatus("cancelled");
        return;
      }
      setError(caught instanceof Error ? caught.message : String(caught));
      setStatus("failed");
    }
  }, [file, upload, wantTranscript, wantAnalysis, targets, query]);

  const tabs = [
    ...(transcribed
      ? [
          {
            id: "transcript",
            label: `Transcript${detectedLanguage ? ` (${detectedLanguage})` : ""}`,
            empty: !transcript,
          },
        ]
      : []),
    ...translations.map((item) => ({ id: item.language, label: item.language, empty: !item.text })),
    ...(analyzed ? [{ id: "analysis", label: "Analysis", empty: !summary }] : []),
  ];
  const hasOutput = tabs.length > 0;
  // What the user picked, if it is still on screen; otherwise the first tab
  // with something in it. Landing on an empty tab while a filled one sits next
  // to it is how a silent video came to look like a total failure.
  const visibleTab =
    (tabs.find((tab) => tab.id === activeTab) ?? tabs.find((tab) => !tab.empty) ?? tabs[0])?.id ??
    "";
  const current = translations.find((item) => item.language === visibleTab);

  return (
    <div className="min-h-svh bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <header className="mb-10">
          <h1 className="text-3xl font-bold tracking-tight">Vida</h1>
          <p className="mt-1 text-slate-600">
            Transcribe, translate, and analyze video.
          </p>
        </header>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,380px)_1fr]">
          {/* ---------------- Controls ---------------- */}
          <section className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div>
              <input
                id="video"
                type="file"
                accept="video/*,audio/*"
                onChange={handleFile}
                className="hidden"
              />
              <label
                htmlFor="video"
                className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-300 p-8 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/40"
              >
                <span className="font-medium text-blue-600">Choose a video or audio file</span>
                <span className="mt-1 text-sm text-slate-500">MP4, MOV, MP3, WAV…</span>
              </label>
            </div>

            {file && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                <p className="truncate font-medium">{file.name}</p>
                <p className="mt-0.5 text-slate-500">
                  {(file.size / 1024 / 1024).toFixed(1)} MB
                  {upload && ` · ${formatDuration(upload.duration)}`}
                  {upload && !upload.has_audio && " · no audio track"}
                </p>
              </div>
            )}

            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-semibold text-slate-700">Output</legend>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={wantTranscript}
                  onChange={(event) => setWantTranscript(event.target.checked)}
                  className="size-4 rounded"
                />
                Transcript with timestamps
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={wantAnalysis}
                  onChange={(event) => setWantAnalysis(event.target.checked)}
                  className="size-4 rounded"
                />
                Visual analysis
              </label>
            </fieldset>

            <div>
              <p className="mb-2 text-sm font-semibold text-slate-700">Translate to</p>
              <div className="flex flex-wrap gap-2">
                {LANGUAGES.map((language) => {
                  const selected = targets.includes(language);
                  return (
                    <button
                      key={language}
                      type="button"
                      onClick={() => toggleTarget(language)}
                      className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                        selected
                          ? "border-blue-600 bg-blue-600 text-white"
                          : "border-slate-300 bg-white text-slate-700 hover:border-blue-400"
                      }`}
                    >
                      {language}
                    </button>
                  );
                })}
              </div>
            </div>

            {wantAnalysis && (
              <input
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Optional: what should the analysis focus on?"
                className="w-full rounded-lg border border-slate-300 p-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30"
              />
            )}

            <div className="flex gap-3">
              <button
                onClick={run}
                disabled={!file || busy}
                className="flex-1 rounded-lg bg-blue-600 px-5 py-3 font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? "Working…" : "Run"}
              </button>
              {busy && (
                <button
                  onClick={() => abortRef.current?.abort()}
                  className="rounded-lg bg-slate-200 px-4 py-3 font-semibold text-slate-700 hover:bg-slate-300"
                >
                  Cancel
                </button>
              )}
            </div>

            {status !== "idle" && (
              <p
                className={`rounded-lg border p-3 text-sm ${
                  status === "failed"
                    ? "border-red-200 bg-red-50 text-red-700"
                    : status === "done"
                      ? "border-green-200 bg-green-50 text-green-700"
                      : "border-blue-200 bg-blue-50 text-blue-700"
                }`}
              >
                {status === "failed"
                  ? error
                  : status === "done"
                    ? "Finished"
                    : status === "cancelled"
                      ? "Cancelled"
                      : status === "uploading"
                        ? "Uploading…"
                        : stage || "Working…"}
              </p>
            )}
          </section>

          {/* ---------------- Results ---------------- */}
          <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
            {!hasOutput ? (
              <div className="flex h-full min-h-80 items-center justify-center p-10 text-center text-slate-400">
                Results will appear here.
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-1 border-b border-slate-200 p-2">
                  {tabs.map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id)}
                      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                        visibleTab === tab.id
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                <div className="p-6">
                  {visibleTab === "analysis" &&
                    (summary ? (
                      <p className="whitespace-pre-wrap leading-relaxed">{summary}</p>
                    ) : (
                      <p className="text-slate-500">
                        The analysis came back empty. That usually means the model had nothing to
                        add — try again, or ask a specific question to focus it.
                      </p>
                    ))}

                  {visibleTab === "transcript" &&
                    (transcript ? (
                      <p className="whitespace-pre-wrap leading-relaxed">{transcript}</p>
                    ) : (
                      <p className="text-slate-500">
                        No speech was detected in this video. Silent clips, music, and background
                        noise all produce an empty transcript.
                      </p>
                    ))}

                  {current && (
                    <>
                      <div className="mb-4 flex justify-end">
                        <button
                          onClick={() =>
                            downloadText(
                              `${(upload?.filename ?? "subtitles").replace(/\.[^.]+$/, "")}.${current.language.toLowerCase()}.srt`,
                              current.srt,
                            )
                          }
                          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
                        >
                          Download .srt
                        </button>
                      </div>
                      <p className="whitespace-pre-wrap leading-relaxed">{current.text}</p>
                    </>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
