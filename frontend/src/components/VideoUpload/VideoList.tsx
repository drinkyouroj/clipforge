import { useState, useEffect } from "react";
import api from "../../api/client";

interface Video {
  id: string;
  original_filename: string;
  status: string;
  duration: number | null;
  created_at: string;
}

export default function VideoList() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetchVideos() {
    try {
      const resp = await api.get("/videos/");
      setVideos(resp.data.videos);
    } catch {
      // silently fail — user might not be logged in
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchVideos();
  }, []);

  if (loading) return <p>Loading videos...</p>;
  if (videos.length === 0) return <p>No videos yet. Upload one above.</p>;

  return (
    <div className="video-list">
      <h2>Your Videos</h2>
      <table>
        <thead>
          <tr>
            <th>Filename</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Uploaded</th>
          </tr>
        </thead>
        <tbody>
          {videos.map((v) => (
            <tr key={v.id}>
              <td>{v.original_filename}</td>
              <td>{v.status}</td>
              <td>{v.duration ? `${Math.round(v.duration)}s` : "—"}</td>
              <td>{new Date(v.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
