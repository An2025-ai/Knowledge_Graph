#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::net::TcpListener;
use std::sync::Mutex;
use tauri::{Manager, State};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[derive(Clone, Serialize)]
struct BackendSession {
    base_url: String,
    token: String,
}

struct AppState {
    session: BackendSession,
    sidecar: Mutex<Option<CommandChild>>,
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
            sidecar: Mutex::new(None),
        })
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![get_backend_session])
        .setup(|app| {
            // `tauri dev` uses scripts/dev-desktop.ps1 to run the Python
            // backend. Release builds own the backend through the sidecar.
            if cfg!(debug_assertions) {
                return Ok(());
            }

            let state = app.state::<AppState>();
            let port = state
                .session
                .base_url
                .rsplit(':')
                .next()
                .expect("backend URL must contain a port");
            let command = app
                .shell()
                .sidecar("knowledge-engine")?
                .args(["--host", "127.0.0.1", "--port", port, "--token", &state.session.token]);
            let (mut events, child) = command.spawn()?;
            state.sidecar.lock().expect("sidecar lock poisoned").replace(child);

            // Drain the pipe so a verbose backend cannot block on stdout.
            tauri::async_runtime::spawn(async move {
                while events.recv().await.is_some() {}
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Brand Atlas");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<AppState>() {
                if let Some(child) = state.sidecar.lock().expect("sidecar lock poisoned").take() {
                    let _ = child.kill();
                }
            }
        }
    });
}
