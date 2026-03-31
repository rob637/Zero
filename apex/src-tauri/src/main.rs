#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};

struct PythonServer(Mutex<Option<Child>>);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(PythonServer(Mutex::new(None)))
        .setup(|app| {
            // Start Python server
            let python_child = start_python_server();
            
            // Store the child process
            let state = app.state::<PythonServer>();
            *state.0.lock().unwrap() = Some(python_child);
            
            // Set up system tray
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
                        // Kill Python server
                        let state: tauri::State<PythonServer> = app.state();
                        if let Some(mut child) = state.0.lock().unwrap().take() {
                            let _ = child.kill();
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
                // Hide to tray instead of closing
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn start_python_server() -> Child {
    // In development, run python directly from the workspace
    #[cfg(debug_assertions)]
    {
        Command::new("python")
            .arg("server.py")
            .current_dir(std::env::current_dir().unwrap().join(".."))
            .spawn()
            .unwrap_or_else(|_| {
                // Fallback: try without changing directory
                Command::new("python")
                    .arg("../server.py")
                    .spawn()
                    .expect("Failed to start Python server")
            })
    }
    
    // In production, the Python server should be bundled or started separately
    #[cfg(not(debug_assertions))]
    {
        // For production, we expect the Python server to be running
        // or bundled as a sidecar. For now, try to start it.
        Command::new("python")
            .arg("server.py")
            .spawn()
            .expect("Failed to start Python server")
    }
}
