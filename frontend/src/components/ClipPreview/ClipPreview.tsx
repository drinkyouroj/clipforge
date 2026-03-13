import { useState, useRef, useEffect } from "react";
import api from "../../api/client";

interface ClipPreviewProps {
  videoId: string;
  startTime: number;
  endTime: number;
}

export default function ClipPreview({ videoId, startTime, endTime }: ClipPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function fetchPreviewUrl() {
      try {
        const resp = await api.get(`/videos/${videoId}/preview-url`);
        setPreviewUrl(resp.data.url);
      } catch {
        setError("Could not load video preview");
      } finally {
        setLoading(false);
      }
    }
    fetchPreviewUrl();
  }, [videoId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !previewUrl) return;

    const handleTimeUpdate = () => {
      if (video.currentTime >= endTime) {
        video.pause();
        video.currentTime = startTime;
      }
    };

    const handleLoadedMetadata = () => {
      video.currentTime = startTime;
    };

    video.addEventListener("timeupdate", handleTimeUpdate);
    video.addEventListener("loadedmetadata", handleLoadedMetadata);

    return () => {
      video.removeEventListener("timeupdate", handleTimeUpdate);
      video.removeEventListener("loadedmetadata", handleLoadedMetadata);
    };
  }, [previewUrl, startTime, endTime]);

  if (loading) return <p>Loading preview...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!previewUrl) return null;

  return (
    <div className="clip-preview">
      <h4>Preview</h4>
      <video
        ref={videoRef}
        src={`${previewUrl}#t=${startTime},${endTime}`}
        controls
        style={{ width: "100%", maxHeight: 400, borderRadius: 8 }}
      />
      <p className="clip-preview__info">
        {startTime.toFixed(1)}s — {endTime.toFixed(1)}s ({(endTime - startTime).toFixed(1)}s)
      </p>
    </div>
  );
}
