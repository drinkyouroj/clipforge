import { useState, useEffect } from "react";
import api from "../../api/client";
import ClipCard from "./ClipCard";

interface Clip {
  id: string;
  start_time: number;
  end_time: number;
  duration: number;
  virality_score: number | null;
  hook: string | null;
  reasoning: string | null;
  clip_type: string | null;
  suggested_title: string | null;
  platform_fit: string[] | null;
  status: string;
}

interface ClipListProps {
  videoId: string;
  onClipSelect: (clip: Clip) => void;
}

export default function ClipList({ videoId, onClipSelect }: ClipListProps) {
  const [clips, setClips] = useState<Clip[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    async function fetchClips() {
      try {
        const resp = await api.get(`/clips/video/${videoId}`);
        setClips(resp.data.clips);
      } catch {
        // Video may not have clips yet
      } finally {
        setLoading(false);
      }
    }
    fetchClips();
  }, [videoId]);

  function handleSelect(clipId: string) {
    setSelectedId(clipId);
    const clip = clips.find((c) => c.id === clipId);
    if (clip) onClipSelect(clip);
  }

  if (loading) return <p>Loading clips...</p>;
  if (clips.length === 0) return <p>No clip candidates yet.</p>;

  return (
    <div className="clip-list">
      <h3>{clips.length} Clip Candidates</h3>
      {clips.map((clip) => (
        <ClipCard
          key={clip.id}
          clip={clip}
          onSelect={handleSelect}
          selected={clip.id === selectedId}
        />
      ))}
    </div>
  );
}
