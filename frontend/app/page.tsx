"use client"
import { useState, useRef } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function VideoUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>('...');
  const [prompt, setPrompt] = useState<string>("");
  const [result, setResult] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      setFile(e.target.files[0]);
      setResult("");
      setStatus('...');
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    abortRef.current = new AbortController();
    setResult("");
    setIsStreaming(true);

    try {
      // Step 1: Upload the file
      setStatus('Uploading...');
      const formData = new FormData();
      formData.append("file", file);
      const uploadRes = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData,
        signal: abortRef.current.signal,
      });

      if (!uploadRes.ok) throw new Error("Upload failed");
      const { video_path } = await uploadRes.json();

      // Step 2: Stream the analysis
      setStatus('Analyzing...');
      const message = prompt.trim()
        ? `Analyze the video at ${video_path}. ${prompt}`
        : `Analyze the video at ${video_path} and summarize its main topic and key events.`;

      const streamRes = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: abortRef.current.signal,
      });

      if (!streamRes.ok) throw new Error("Analysis failed");

      const reader = streamRes.body!.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const lines = decoder.decode(value).split("\n\n");
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") break;
          try {
            const parsed = JSON.parse(data);
            if (parsed.error) throw new Error(parsed.error);
            if (parsed.chunk) setResult(prev => prev + parsed.chunk);
          } catch { /* incomplete JSON chunk, skip */ }
        }
      }

      setStatus('Completed');
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        setStatus('Cancelled');
      } else {
        console.error(err);
        setStatus('Failed');
      }
    } finally {
      setIsStreaming(false);
    }
  };

  const handleCancel = () => {
    abortRef.current?.abort();
  };

  const isProcessing = isStreaming;
  const statusStyle =
    status === 'Failed' ? 'bg-red-50 border-red-200 text-red-700' :
    status === 'Completed' ? 'bg-green-50 border-green-200 text-green-700' :
    status === 'Cancelled' ? 'bg-yellow-50 border-yellow-200 text-yellow-700' :
    'bg-blue-50 border-blue-200 text-blue-700';

  return (
    <div className="min-h-svh bg-linear-to-br from-slate-50 to-slate-100 p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-4xl font-bold text-slate-900 mb-2">VidA</h1>
          <p className="text-slate-600">Upload and analyze your videos with AI-powered insights</p>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Upload Section */}
          <div className="bg-white rounded-xl shadow-lg p-8 border border-slate-200">
            <div className="flex items-center mb-6">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center mr-3">
                <span className="text-blue-600 font-bold">1</span>
              </div>
              <h2 className="text-2xl font-semibold text-slate-900">Upload Video</h2>
            </div>

            <div className="space-y-6">
              {/* File Input */}
              <div>
                <input
                  id="videoUpload"
                  type="file"
                  accept="video/*"
                  required
                  onChange={handleFileChange}
                  className="hidden"
                />
                <label
                  htmlFor="videoUpload"
                  className="flex flex-col items-center justify-center w-full p-8 border-2 border-dashed border-blue-300 rounded-lg cursor-pointer hover:bg-blue-50 transition-colors bg-blue-50/30"
                >
                  <div className="text-center">
                    <svg className="w-12 h-12 text-blue-600 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    <p className="text-blue-600 font-semibold">Select a video file</p>
                    <p className="text-slate-500 text-sm mt-1">or drag and drop</p>
                  </div>
                </label>
              </div>

              {/* File Selected Display */}
              {file && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                  <p className="text-green-800">
                    <span className="font-semibold">✓ Selected:</span> {file.name}
                  </p>
                  <p className="text-green-700 text-sm mt-1">
                    {(file.size / (1024 * 1024)).toFixed(2)} MB
                  </p>
                </div>
              )}

              {/* Prompt Input */}
              <div>
                <input
                  type="text"
                  title="prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Ask something about the video (optional)"
                  className="w-full p-4 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-black"
                />
              </div>

              {/* Status */}
              {status !== '...' && (
                <div className={`rounded-lg p-4 border ${statusStyle}`}>
                  <p className="flex items-center gap-2">
                    {isProcessing && (
                      <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                      </svg>
                    )}
                    {status}
                  </p>
                </div>
              )}

              {/* Buttons */}
              <div className="flex gap-3">
                <button
                  onClick={handleUpload}
                  disabled={!file || isProcessing}
                  className="flex-1 px-6 py-3 bg-linear-to-r from-blue-600 to-blue-700 text-white font-semibold rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg"
                >
                  {isProcessing ? 'Processing...' : 'Upload and Analyze'}
                </button>
                {isProcessing && (
                  <button
                    onClick={handleCancel}
                    className="px-4 py-3 bg-slate-200 text-slate-700 font-semibold rounded-lg hover:bg-slate-300 transition-all"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Result Section */}
          <div className="bg-white rounded-xl shadow-lg p-8 border border-slate-200 flex flex-col">
            <div className="flex items-center mb-6">
              <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center mr-3">
                <span className="text-green-600 font-bold">2</span>
              </div>
              <h2 className="text-2xl font-semibold text-slate-900">Results</h2>
              {result && (
                <button
                  onClick={() => navigator.clipboard.writeText(result)}
                  className="ml-auto text-sm text-slate-500 hover:text-slate-700 flex items-center gap-1"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  Copy
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto">
              {result ? (
                <div className="prose prose-slate max-w-none">
                  <p className="text-slate-700 whitespace-pre-wrap leading-relaxed">{result}</p>
                  {isStreaming && (
                    <span className="inline-block w-2 h-4 bg-blue-500 animate-pulse ml-1 rounded-sm" />
                  )}
                </div>
              ) : (
                <div className="flex items-center justify-center h-64 text-center">
                  <div>
                    <svg className="w-16 h-16 text-slate-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <p className="text-slate-500 font-medium">Upload a video to see results</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}