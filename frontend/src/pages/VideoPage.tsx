import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../api/client";
import ClipList from "../components/ClipCandidates/ClipList";
import JobProgress from "../components/VideoUpload/JobProgress";

interface Video {
  id: string;
  original_filename: string;
  status: string;
  duration: number | null;
}

export default function VideoPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();
  const [video, setVideo] = useState<Video | null>(null);
  const [selectedClip, setSelectedClip] = useState<any>(null);
  const [detectJobId, setDetectJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    async function fetchVideo() {
      try {
        const resp = await api.get(`/videos/${videoId}`);
        setVideo(resp.data);
      } catch {
        navigate("/");
      } finally {
        setLoading(false);
      }
    }
    fetchVideo();
  }, [videoId, navigate]);

  async function handleDetectClips() {
    if (!videoId) return;
    try {
      const resp = await api.post(`/clips/detect/${videoId}`);
      if (resp.data.job_id) {
        setDetectJobId(resp.data.job_id);
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to start clip detection");
    }
  }

  if (loading) return <p>Loading...</p>;
  if (!video) return <p>Video not found.</p>;

  return (
    <div className="video-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back to Dashboard
      </button>

      <h2>{video.original_filename}</h2>
      <p>
        Status: <strong>{video.status}</strong>
        {video.duration && <> | Duration: {Math.round(video.duration)}s</>}
      </p>

      {video.status === "ready" && !detectJobId && (
        <button onClick={handleDetectClips} className="detect-btn">
          Detect Viral Clips
        </button>
      )}

      {detectJobId && (
        <JobProgress
          jobId={detectJobId}
          onComplete={() => {
            setDetectJobId(null);
            setRefreshKey((k) => k + 1);
          }}
        />
      )}

      {selectedClip && (
        <div className="clip-preview-info">
          <h3>Selected: {selectedClip.suggested_title || "Untitled Clip"}</h3>
          <p>
            {Math.round(selectedClip.start_time)}s –{" "}
            {Math.round(selectedClip.end_time)}s ({Math.round(selectedClip.duration)}s)
          </p>
        </div>
      )}

      {videoId && (
        <ClipList
          key={refreshKey}
          videoId={videoId}
          onClipSelect={setSelectedClip}
        />
      )}
    </div>
  );
}
