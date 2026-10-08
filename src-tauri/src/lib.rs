use std::sync::{Arc, Mutex};
use std::time::Duration;

use rand::Rng;
use serde::Serialize;
use tauri::{
    Emitter, Manager, RunEvent, WindowEvent,
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
};
use tauri_plugin_shell::ShellExt;
#[derive(Clone, Serialize)]
struct SidecarReady {
    url: String,
    token: String,
}

#[derive(Clone, Serialize)]
struct SidecarFailed {
    reason: String,
}

/// Holds the running sidecar child so we can kill it on exit.
struct SidecarState(Arc<Mutex<Option<tauri_plugin_shell::process::CommandChild>>>);

fn generate_token() -> String {
    let mut rng = rand::thread_rng();
    let bytes: [u8; 32] = rng.gen();
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[tauri::command]
fn get_sidecar_config(app: tauri::AppHandle) -> Option<SidecarReady> {
    app.try_state::<SidecarReady>().map(|s| (*s).clone())
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    tauri_plugin_opener::open_path(path, None::<String>).map_err(|e| e.to_string())
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    tauri_plugin_opener::reveal_item_in_dir(path).map_err(|e| e.to_string())
}
pub fn run() {
    let sidecar_state = SidecarState(Arc::new(Mutex::new(None)));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .manage(sidecar_state)
        .invoke_handler(tauri::generate_handler![get_sidecar_config, open_path, reveal_path])
        .setup(|app| {
            let handle = app.handle().clone();

            // Tray icon with context menu — mascot.png is bundled as the window icon,
            // tray uses the same resource.
            if let Ok(show) = MenuItemBuilder::with_id("tray_show", "Exibir / Ocultar Zfrog").build(app) {
                if let Ok(quick) = MenuItemBuilder::with_id("tray_quick", "Novo Jump (Captura Rápida)").build(app) {
                    if let Ok(folder) = MenuItemBuilder::with_id("tray_folder", "Abrir Pasta de Referências").build(app) {
                        if let Ok(quit) = MenuItemBuilder::with_id("tray_quit", "Sair").build(app) {
                            if let Ok(menu) = MenuBuilder::new(app)
                                .items(&[&show, &quick, &folder, &quit])
                                .build()
                            {
                                let menu_handle = handle.clone();
                                let _ = TrayIconBuilder::new()
                                    .icon(app.default_window_icon().cloned().unwrap())
                                    .menu(&menu)
                                    .show_menu_on_left_click(false)
                                    .on_menu_event(move |app, event| match event.id().as_ref() {
                                        "tray_show" => {
                                            if let Some(win) = app.get_webview_window("main") {
                                                let _ = if win.is_visible().unwrap_or(true) {
                                                    win.hide()
                                                } else {
                                                    win.show().and_then(|_| win.set_focus())
                                                };
                                            }
                                        }
                                        "tray_quick" => {
                                            if let Some(win) = app.get_webview_window("main") {
                                                let _ = win.show().and_then(|_| win.set_focus());
                                                let _ = win.emit("tray-quick-jump", ());
                                            }
                                        }
                                        "tray_folder" => {
                                            let dir = resolve_data_dir();
                                            let _ = tauri_plugin_opener::open_path(
                                                dir.to_string_lossy().to_string(),
                                                None::<String>,
                                            );
                                        }
                                        "tray_quit" => {
                                            kill_sidecar(app);
                                            app.exit(0);
                                        }
                                        _ => {}
                                    })
                                    .on_tray_icon_event(|tray, event| {
                                        let app = tray.app_handle();
                                        if let TrayIconEvent::Click { button: MouseButton::Left, .. } = event {
                                            if let Some(win) = app.get_webview_window("main") {
                                                let _ = win.show().and_then(|_| win.set_focus());
                                            }
                                        }
                                    })
                                    .build(&menu_handle);
                            }
                        }
                    }
                }
            }

            // All sidecar + window wiring happens off the setup thread so we do
            // not block the window from appearing.
            let handle_for_sidecar = handle.clone();
            tauri::async_runtime::spawn(async move {
                start_sidecar(handle_for_sidecar).await;
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| match event {
            RunEvent::WindowEvent { label, event, .. } => {
                if let WindowEvent::CloseRequested { .. } = event {
                    kill_sidecar(app_handle);
                }
                let _ = label;
            }
            RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                kill_sidecar(app_handle);
            }
            _ => {}
        });
}

async fn start_sidecar(app: tauri::AppHandle) {
    let port = match portpicker::pick_unused_port() {
        Some(p) => p,
        None => {
            let _ = app.emit(
                "sidecar-failed",
                SidecarFailed {
                    reason: "No free port available for sidecar".into(),
                },
            );
            return;
        }
    };

    let token = generate_token();
    let url = format!("http://127.0.0.1:{port}");
    let ready_payload = SidecarReady {
        url: url.clone(),
        token: token.clone(),
    };

    // Make it available via `invoke("get_sidecar_config")` even before the
    // event arrives (race between frontend mount and sidecar boot).
    app.manage(ready_payload.clone());

    // Resolve data dir: XDG on Linux, APPDATA on Windows. Keep in sync with
    // `src/zfrog/desktop_entry.py` and `src/zfrog/config.py:data_dir`.
    let data_dir = resolve_data_dir();

    let sidecar_cmd = app
        .shell()
        .sidecar("zfrog-api")
        .expect("sidecar binary `zfrog-api` not found — run `python scripts/build-sidecar.py` first");

    let sidecar_cmd = sidecar_cmd
        .args([
            "--port",
            &port.to_string(),
            "--auth-token",
            &token,
            "--data-dir",
            &data_dir.to_string_lossy().to_string(),
        ])
        .env("ZFROG_DATA_DIR", data_dir.to_string_lossy().to_string());

    let (mut rx, child) = match sidecar_cmd.spawn() {
        Ok(pair) => pair,
        Err(e) => {
            let _ = app.emit(
                "sidecar-failed",
                SidecarFailed {
                    reason: format!("Failed to spawn sidecar: {e}"),
                },
            );
            return;
        }
    };

    // Keep child handle so `kill_sidecar` can terminate it on window close.
    if let Some(state) = app.try_state::<SidecarState>() {
        if let Ok(mut guard) = state.0.lock() {
            *guard = Some(child);
        }
    }

    // Forward sidecar stdout/stderr to the app log (useful in dev).
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Stdout(line) | CommandEvent::Stderr(line) = event {
                let text = String::from_utf8_lossy(&line);
                if !text.trim().is_empty() {
                    eprintln!("[sidecar] {}", text.trim_end());
                }
            }
        }
    });

    // Poll /health until it answers or we time out (8s per PLANO-TAURI.md).
    let health_url = format!("{url}/health");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_millis(800))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new());

    let mut ok = false;
    for _ in 0..16 {
        tokio::time::sleep(Duration::from_millis(500)).await;
        match client.get(&health_url).send().await {
            Ok(resp) if resp.status().is_success() => {
                ok = true;
                break;
            }
            _ => continue,
        }
    }

    if ok {
        let _ = app.emit("sidecar-ready", ready_payload);
    } else {
        let _ = app.emit(
            "sidecar-failed",
            SidecarFailed {
                reason: format!("Sidecar did not become healthy at {health_url} within 8s"),
            },
        );
    }
}

fn kill_sidecar(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<SidecarState>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

fn resolve_data_dir() -> std::path::PathBuf {
    if let Ok(dir) = std::env::var("ZFROG_DATA_DIR") {
        if !dir.trim().is_empty() {
            return std::path::PathBuf::from(dir);
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Ok(appdata) = std::env::var("APPDATA") {
            return std::path::PathBuf::from(appdata).join("zfrog");
        }
    }
    // Linux / fallback: XDG_DATA_HOME or ~/.local/share/zfrog
    if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
        if !xdg.trim().is_empty() {
            return std::path::PathBuf::from(xdg).join("zfrog");
        }
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    std::path::PathBuf::from(home)
        .join(".local")
        .join("share")
        .join("zfrog")
}
