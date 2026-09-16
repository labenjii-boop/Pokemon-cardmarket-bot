export function PlaceholderScreen({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center p-6 text-center">
      <h1 className="mb-2 text-xl font-semibold">{title}</h1>
      <p className="max-w-md text-[var(--color-text-muted)]">
        Not built yet — scheduled for {phase} of the build plan (see Section 13 of the build
        spec / repo README).
      </p>
    </div>
  );
}
