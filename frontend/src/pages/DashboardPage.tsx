import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import UploadForm from "../components/VideoUpload/UploadForm";
import VideoList from "../components/VideoUpload/VideoList";
import JobProgress from "../components/VideoUpload/JobProgress";

export default function DashboardPage() {
  const navigate = useNavigate();
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  function handleUploadComplete(video: any) {
    if (video.job_id) {
      setActiveJobId(video.job_id);
    }
    setRefreshKey((k) => k + 1);
  }

  const handleJobComplete = useCallback(() => {
    setActiveJobId(null);
    setRefreshKey((k) => k + 1);
  }, []);

  async function handleLogout() {
    await api.post("/auth/logout");
    navigate("/login");
  }

  return (
    <div className="dashboard">
      <header>
        <h1>ClipForge</h1>
        <button onClick={handleLogout}>Log out</button>
      </header>
      <UploadForm onUploadComplete={handleUploadComplete} />
      {activeJobId && (
        <JobProgress jobId={activeJobId} onComplete={handleJobComplete} />
      )}
      <VideoList key={refreshKey} />
    </div>
  );
}
