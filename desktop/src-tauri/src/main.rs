#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, State, WindowEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Clone, Serialize)]
struct BackendSession {
    base_url: String,
    token: String,
}

enum BackendProcess {
    Python(Child),
    Sidecar(CommandChild),
}

struct AppState {
    session: BackendSession,
    backend: Mutex<Option<BackendProcess>>,
}

#[tauri::command]
fn get_backend_session(state: State<'_, AppState>) -> BackendSession {
    state.session.clone()
}

fn free_local_port() -> u16 {
    TcpListener::bind(("127.0.0.1", 0))
        .expect("unable to reserve a local port")
        .local_addr()
        .expect("unable to read local port")
        .port()
}

fn stop_backend(state: &AppState) {
    let process = state.backend.lock().expect("backend lock poisoned").take();
    match process {
        Some(BackendProcess::Python(mut child)) => {
            let _ = child.kill();
            let _ = child.wait();
        }
        Some(BackendProcess::Sidecar(child)) => {
            let _ = child.kill();
        }
        None => {}
    }
}

fn main() {
    let (port, token) = if cfg!(debug_assertions) {
        (8787, "dev-token".to_owned())
    } else {
        (free_local_port(), uuid::Uuid::new_v4().to_string())
    };
    let session = BackendSession {
        base_url: format!("http://127.0.0.1:{port}"),
        token,
    };

    let app = tauri::Builder::default()
        .manage(AppState {
            session,
            backend: Mutex::new(None),
        })
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![get_backend_session])
        .setup(|app| {
            let state = app.state::<AppState>();
            let port = state
                .session
                .base_url
                .rsplit(':')
                .next()
                .expect("backend URL must contain a port");

            if cfg!(debug_assertions) {
                // Development mode also belongs to Tauri's process lifetime.
                // Do not launch this from beforeDevCommand, otherwise closing
                // the window leaves Python holding the SQLite file open.
                let repo_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("..")
                    .join("..");
                let mut command = Command::new("python");
                command
                    .args([
                        "-m",
                        "backend.main",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        port,
                        "--token",
                        &state.session.token,
                    ])
                    .current_dir(repo_root)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                #[cfg(windows)]
                command.creation_flags(0x08000000); // CREATE_NO_WINDOW
                let child = command.spawn()?;
                state
                    .backend
                    .lock()
                    .expect("backend lock poisoned")
                    .replace(BackendProcess::Python(child));
                return Ok(());
            }

            let command = app.shell().sidecar("knowledge-engine")?.args([
                "--host",
                "127.0.0.1",
                "--port",
                port,
                "--token",
                &state.session.token,
            ]);
            let (mut events, child) = command.spawn()?;
            state
                .backend
                .lock()
                .expect("backend lock poisoned")
                .replace(BackendProcess::Sidecar(child));

            // Drain the pipe so a verbose backend cannot block on stdout.
            tauri::async_runtime::spawn(async move { while events.recv().await.is_some() {} });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.app_handle().try_state::<AppState>() {
                    stop_backend(&state);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Brand Atlas");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            if let Some(state) = app_handle.try_state::<AppState>() {
                stop_backend(&state);
            }
        }
    });
}
