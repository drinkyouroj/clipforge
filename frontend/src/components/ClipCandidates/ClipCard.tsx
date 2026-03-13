interface ClipCardProps {
  clip: {
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
  };
  onSelect: (clipId: string) => void;
  selected: boolean;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function scoreColor(score: number): string {
  if (score >= 80) return "#16a34a";
  if (score >= 60) return "#ca8a04";
  return "#dc2626";
}

const TYPE_LABELS: Record<string, string> = {
  insight: "Insight",
  story: "Story",
  controversy: "Controversy",
  "how-to": "How-To",
  emotion: "Emotion",
  humor: "Humor",
};

export default function ClipCard({ clip, onSelect, selected }: ClipCardProps) {
  const score = clip.virality_score ?? 0;

  return (
    <div
      className={`clip-card ${selected ? "clip-card--selected" : ""}`}
      onClick={() => onSelect(clip.id)}
    >
      <div className="clip-card__header">
        <span className="clip-card__title">
          {clip.suggested_title || `Clip ${formatTime(clip.start_time)}`}
        </span>
        {clip.clip_type && (
          <span className="clip-card__type">
            {TYPE_LABELS[clip.clip_type] || clip.clip_type}
          </span>
        )}
      </div>

      <div className="clip-card__score-row">
        <div className="clip-card__score-bar">
          <div
            className="clip-card__score-fill"
            style={{ width: `${score}%`, backgroundColor: scoreColor(score) }}
          />
        </div>
        <span className="clip-card__score-label">{score}</span>
      </div>

      {clip.hook && <p className="clip-card__hook">"{clip.hook}"</p>}

      <div className="clip-card__meta">
        <span>
          {formatTime(clip.start_time)} – {formatTime(clip.end_time)} ({Math.round(clip.duration)}s)
        </span>
        {clip.platform_fit && (
          <span className="clip-card__platforms">
            {clip.platform_fit.join(", ")}
          </span>
        )}
      </div>

      {clip.reasoning && (
        <p className="clip-card__reasoning">{clip.reasoning}</p>
      )}
    </div>
  );
}
