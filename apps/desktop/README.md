# apps/desktop

The Tauri + React + TypeScript + Vite + Tailwind desktop shell (Section 10 of the build spec).
This directory owns the window and the frontend; the actual application logic (catalog,
connectors, ranking) lives in `../backend` and runs as a Tauri sidecar process — see
`src-tauri/src/lib.rs` for how the two are wired together.

## Development

```bash
npm install
npm run dev          # Vite dev server only, on http://localhost:1420
npm run tauri dev    # full app: spawns the window AND the backend sidecar (needs the sidecar
                      # binary built first — see ../backend/scripts/build_sidecar.py)
```

`npm run dev` alone is enough while working on the UI against a backend you're running
separately with `python -m app.entrypoint` (see `../backend/README.md`) — the frontend talks to
`http://127.0.0.1:8756` regardless of whether that backend is a sidecar or a plain `python`
process.

## Structure

- `src/screens/` — one component per core screen (Section 11). Only `Top100.tsx` and
  `SourceStatus.tsx` are wired to real data as of Phase 2; the rest render a placeholder
  naming which build phase covers them.
- `src/api/client.ts` — the only place that calls the backend's HTTP API. Screens import from
  here, never `fetch` directly.
- `src-tauri/` — the Rust shell: window config (`tauri.conf.json`), sidecar lifecycle
  (`src/lib.rs`), and the OS permission grants a sidecar needs to run (`capabilities/`).

## Packaging (Phase 11 — not done yet)

`tauri.conf.json`'s `bundle.targets` is set to `["dmg", "app"]` for an unsigned macOS build.
Building the actual `.dmg` requires running `npm run tauri build` **on the target Mac**
(Apple Silicon and Intel each need their own sidecar binary — there is no cross-compiling
PyInstaller from Linux). Step-by-step Gatekeeper bypass instructions for the unsigned build will
be written into the top-level README once Phase 11 is reached.
