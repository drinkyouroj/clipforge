import { useState, useEffect } from "react";
import api from "../../api/client";
import JobProgress from "../VideoUpload/JobProgress";

interface ExportPanelProps {
  clipId: string;
  clipStatus: string;
  onExportComplete: () => void;
}

interface ExportRecord {
  id: string;
  platform: string;
  aspect_ratio: string;
  resolution: string;
  status: string;
  job_id: string | null;
  download_url: string | null;
}

const PLATFORMS = [
  { key: "shorts", label: "YouTube Shorts", ratio: "9:16" },
  { key: "tiktok", label: "TikTok", ratio: "9:16" },
  { key: "reels", label: "Instagram Reels", ratio: "9:16" },
  { key: "square", label: "Instagram Square", ratio: "1:1" },
  { key: "twitter", label: "X (Twitter)", ratio: "16:9" },
];

export default function ExportPanel({ clipId, clipStatus, onExportComplete }: ExportPanelProps) {
  const [selectedPlatform, setSelectedPlatform] = useState("shorts");
  const [exporting, setExporting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchExports();
  }, [clipId]);

  async function fetchExports() {
    try {
      const resp = await api.get(`/exports/clip/${clipId}`);
      setExports(resp.data.exports);
    } catch {
      // No exports yet
    }
  }

  async function handleExport() {
    setExporting(true);
    setError("");
    try {
      const resp = await api.post("/exports", {
        clip_id: clipId,
        platform: selectedPlatform,
      });
      if (resp.data.job_id) {
        setActiveJobId(resp.data.job_id);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function handleJobComplete() {
    setActiveJobId(null);
    fetchExports();
    onExportComplete();
  }

  if (clipStatus !== "selected") return null;

  return (
    <div className="export-panel">
      <h4>Export Clip</h4>

      <div className="export-panel__platforms">
        {PLATFORMS.map((p) => (
          <button
            key={p.key}
            className={`export-panel__platform-btn ${selectedPlatform === p.key ? "export-panel__platform-btn--active" : ""}`}
            onClick={() => setSelectedPlatform(p.key)}
          >
            <span className="export-panel__platform-label">{p.label}</span>
            <span className="export-panel__platform-ratio">{p.ratio}</span>
          </button>
        ))}
      </div>

      <button
        onClick={handleExport}
        disabled={exporting || !!activeJobId}
        className="export-btn"
      >
        {exporting ? "Starting..." : activeJobId ? "Rendering..." : "Export"}
      </button>

      {error && <p className="error">{error}</p>}

      {activeJobId && (
        <JobProgress jobId={activeJobId} onComplete={handleJobComplete} />
      )}

      {exports.length > 0 && (
        <div className="export-panel__history">
          <h5>Export History</h5>
          {exports.map((exp) => (
            <div key={exp.id} className="export-panel__item">
              <span>{PLATFORMS.find((p) => p.key === exp.platform)?.label || exp.platform}</span>
              <span className="export-panel__item-status">{exp.status}</span>
              {exp.download_url && exp.status === "rendered" && (
                <a href={exp.download_url} download className="download-btn">
                  Download
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
