import { useState, useEffect } from "react";
import api from "../../api/client";

interface JobProgressProps {
  jobId: string;
  onComplete: () => void;
}

export default function JobProgress({ jobId, onComplete }: JobProgressProps) {
  const [status, setStatus] = useState("pending");
  const [error, setError] = useState("");

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const resp = await api.get(`/jobs/${jobId}`);
        setStatus(resp.data.status);
        if (resp.data.status === "completed") {
          clearInterval(interval);
          onComplete();
        } else if (resp.data.status === "failed") {
          clearInterval(interval);
          setError(resp.data.error_message || "Job failed");
        }
      } catch {
        clearInterval(interval);
        setError("Failed to check job status");
      }
    }, 3000); // Poll every 3 seconds

    return () => clearInterval(interval);
  }, [jobId, onComplete]);

  return (
    <div className="job-progress">
      <p>
        Transcription: <strong>{status}</strong>
      </p>
      {status === "pending" && <p>Waiting to start...</p>}
      {status === "running" && <p>Processing your video...</p>}
      {status === "completed" && <p>Done!</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
