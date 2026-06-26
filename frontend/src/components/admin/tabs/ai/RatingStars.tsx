import type { ModelRating } from "./aiUtils";

/** Stars with color by context: gold = text rating, indigo = vision rating. Elo shown in tooltip. */
export function RatingStars({ rating, forVision }: { rating: ModelRating; forVision: boolean }) {
  if (rating.stars === 0) return null;
  const color = forVision ? "#818cf8" : "#f59e0b";
  const tooltip = rating.elo
    ? `Arena Elo: ${rating.elo} · ${rating.stars}/5`
    : `${rating.stars}/5`;
  return (
    <span style={{ fontSize: 11, color, letterSpacing: 1, flexShrink: 0 }} title={tooltip}>
      {"★".repeat(rating.stars)}{"☆".repeat(5 - rating.stars)}
    </span>
  );
}
