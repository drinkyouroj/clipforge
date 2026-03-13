import { useState } from "react";
import api from "../../api/client";

interface ClipAdjusterProps {
  clip: {
    id: string;
    start_time: number;
    end_time: number;
    duration: number;
    suggested_title: string | null;
  };
  videoDuration: number;
  onUpdate: () => void;
}

export default function ClipAdjuster({ clip, videoDuration, onUpdate }: ClipAdjusterProps) {
  const [startTime, setStartTime] = useState(clip.start_time);
  const [endTime, setEndTime] = useState(clip.end_time);
  const [saving, setSaving] = useState(false);

  const duration = Math.max(0, endTime - startTime);
  const isValid = startTime >= 0 && endTime > startTime && endTime <= videoDuration && duration >= 15 && duration <= 90;

  async function handleSave() {
    if (!isValid) return;
    setSaving(true);
    try {
      await api.patch(`/clips/${clip.id}`, {
        start_time: startTime,
        end_time: endTime,
      });
      onUpdate();
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to update clip");
    } finally {
      setSaving(false);
    }
  }

  function formatTime(s: number): string {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  return (
    <div className="clip-adjuster">
      <h4>Adjust: {clip.suggested_title || "Clip"}</h4>

      <div className="clip-adjuster__timeline">
        <div
          className="clip-adjuster__range"
          style={{
            left: `${(startTime / videoDuration) * 100}%`,
            width: `${(duration / videoDuration) * 100}%`,
          }}
        />
      </div>

      <div className="clip-adjuster__controls">
        <label>
          Start: {formatTime(startTime)}
          <input
            type="range"
            min={0}
            max={videoDuration}
            step={0.5}
            value={startTime}
            onChange={(e) => setStartTime(Number(e.target.value))}
          />
        </label>
        <label>
          End: {formatTime(endTime)}
          <input
            type="range"
            min={0}
            max={videoDuration}
            step={0.5}
            value={endTime}
            onChange={(e) => setEndTime(Number(e.target.value))}
          />
        </label>
      </div>

      <div className="clip-adjuster__info">
        <span>Duration: {duration.toFixed(1)}s</span>
        {!isValid && (
          <span className="error">
            {duration < 15 ? "Min 15s" : duration > 90 ? "Max 90s" : "Invalid range"}
          </span>
        )}
      </div>

      <button onClick={handleSave} disabled={!isValid || saving} className="save-btn">
        {saving ? "Saving..." : "Save Changes"}
      </button>
    </div>
  );
}
