// TCGdex's `image` field is a base path with no quality/format suffix — the actual asset lives
// at "<base>/<quality>.<ext>" (Section 10: "Image storage: local folder cache" will replace this
// hotlinking with a real download + cache later; for now this talks straight to TCGdex's CDN).
// webp first (their documented default), falling back to png once, since not every quality/
// format combination is guaranteed to exist for every card.
export function CardImage({
  src,
  alt,
  quality = "high",
  className,
}: {
  src: string | null;
  alt: string;
  quality?: "high" | "low";
  className?: string;
}) {
  if (!src) return null;
  return (
    <img
      src={`${src}/${quality}.webp`}
      onError={(e) => {
        const img = e.currentTarget;
        if (img.dataset.fallback !== "1") {
          img.dataset.fallback = "1";
          img.src = `${src}/${quality}.png`;
        }
      }}
      alt={alt}
      className={className}
      loading="lazy"
    />
  );
}
