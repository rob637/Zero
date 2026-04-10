#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::process::Child;
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};
use tauri_plugin_shell::ShellExt;

struct PythonServer(Mutex<Option<PythonChild>>);

/// Wraps either a std::process::Child or a Tauri sidecar child.
enum PythonChild {
    Std(Child),
    Sidecar(tauri_plugin_shell::process::CommandChild),
}

impl PythonChild {
    fn kill(&mut self) {
        match self {
            PythonChild::Std(c) => { let _ = c.kill(); }
            PythonChild::Sidecar(c) => { let _ = c.kill(); }
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(PythonServer(Mutex::new(None)))
        .setup(|app| {
            // Start Python backend
            let child = start_backend(app)?;
            let state = app.state::<PythonServer>();
            *state.0.lock().unwrap() = Some(child);

            // System tray
            let show_item = MenuItem::with_id(app, "show", "Show Telic", true, None::<&str>)?;
            let hide_item = MenuItem::with_id(app, "hide", "Hide to Tray", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[&show_item, &hide_item, &quit_item])?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "hide" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.hide();
                        }
                    }
                    "quit" => {
                        let state: tauri::State<PythonServer> = app.state();
                        if let Some(mut child) = state.0.lock().unwrap().take() {
                            child.kill();
                        }
                        std::process::exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn start_backend(app: &tauri::App) -> Result<PythonChild, Box<dyn std::error::Error>> {
    // Production: use bundled sidecar (PyInstaller-built apex-server)
    #[cfg(not(debug_assertions))]
    {
        let sidecar = app.shell().sidecar("apex-server")
            .map_err(|e| format!("Sidecar not found: {e}"))?;
        let (_, child) = sidecar.spawn()
            .map_err(|e| format!("Failed to start backend: {e}"))?;
        Ok(PythonChild::Sidecar(child))
    }

    // Development: run python directly
    #[cfg(debug_assertions)]
    {
        let _ = app; // unused in dev
        let child = std::process::Command::new("python")
            .arg("server.py")
            .current_dir(std::env::current_dir().unwrap())
            .spawn()
            .or_else(|_| {
                std::process::Command::new("python3")
                    .arg("server.py")
                    .current_dir(std::env::current_dir().unwrap())
                    .spawn()
            })
            .map_err(|e| format!("Failed to start Python server: {e}"))?;
        Ok(PythonChild::Std(child))
    }
}
