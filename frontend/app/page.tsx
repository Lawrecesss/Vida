"use client"
import { useState, useEffect } from "react";

export default function VideoUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>('...');

  const [prompt, setPrompt] = useState<string>("");
  const [tags, setTags] = useState<string[]>([]);

  // Initialize client once
  
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) setFile(e.target.files[0]);
  };

  const handleUpload = async () => {
    if (!file) return;

    try {
      setStatus('Uploading...');
      setStatus('Waiting for result...');
      setStatus('Processing completed');
    } catch (err) {
      console.error(err);
      setStatus('Upload or processing failed');
    }
  };
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
                  placeholder="Prompt"
                  className="w-full p-4 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-black"
                />
              </div>
              {/* Status */}
              <div className={`rounded-lg p-4 ${status.includes('failed') ? 'bg-red-50 border border-red-200' : status.includes('completed') ? 'bg-green-50 border border-green-200' : 'bg-blue-50 border border-blue-200'}`}>
                <p className={status.includes('failed') ? 'text-red-700' : status.includes('completed') ? 'text-green-700' : 'text-blue-700'}>
                  {status}
                </p>
              </div>

              {/* Upload Button */}
              <button
                onClick={handleUpload}
                disabled={!file || status === 'Uploading...' || status === 'Waiting for result...'}
                className="w-full px-6 py-3 bg-linear-to-r from-blue-600 to-blue-700 text-white font-semibold rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg"
              >
                {status === 'Uploading...' || status === 'Waiting for result...' ? 'Processing...' : 'Upload and Analyze'}
              </button>
            </div>
          </div>

          {/* Result Section */}
          <div className="bg-white rounded-xl shadow-lg p-8 border border-slate-200">
            <div className="flex items-center mb-6">
              <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center mr-3">
                <span className="text-green-600 font-bold">2</span>
              </div>
              <h2 className="text-2xl font-semibold text-slate-900">Results</h2>
            </div>
              <div className="flex items-center justify-center h-64 text-center">
                <div>
                  <svg className="w-16 h-16 text-slate-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p className="text-slate-500 font-medium">Upload a video to see results</p>
                </div>
              </div>
          </div>
        </div>
      </div>
    </div>
  );
}