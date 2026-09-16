// Tauri shell: owns the native window and the lifecycle of the Python (FastAPI) sidecar.
// The sidecar is the app's actual backend (Section 10 of the build spec) — this file's only
// job is to start it when the window opens and stop it when the window closes, and to surface
// its stdout/stderr in the same log stream as the Rust side for the Settings > Logs screen.
use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct BackendProcess(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // The FastAPI backend is packaged as a PyInstaller sidecar binary named
            // `pokemon-card-tracker-backend-<target-triple>` (see apps/backend/README.md for
            // the build step). It listens on localhost only; the frontend talks to it over
            // HTTP/WebSocket on a fixed local port defined in apps/backend/app/config.py.
            let sidecar = app.shell().sidecar("pokemon-card-tracker-backend")?;
            let (mut rx, child) = sidecar.spawn().expect("failed to start backend sidecar");

            app.state::<BackendProcess>()
                .0
                .lock()
                .unwrap()
                .replace(child);

            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            log::info!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            log::warn!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Error(err) => {
                            log::error!("[backend] sidecar error: {err}");
                        }
                        CommandEvent::Terminated(payload) => {
                            log::warn!("[backend] exited: {payload:?}");
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Make sure the Python process never outlives the window (Section 7 background
            // collection is a separate, explicit setting — this is just plain shutdown).
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(child) = app_handle.state::<BackendProcess>().0.lock().unwrap().take()
                {
                    let _ = child.kill();
                }
            }
        });
}
