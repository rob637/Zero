#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{
    CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    WindowBuilder, WindowUrl,
};

struct PythonServer(Mutex<Option<Child>>);

fn main() {
    // System tray menu
    let show = CustomMenuItem::new("show".to_string(), "Show Apex");
    let hide = CustomMenuItem::new("hide".to_string(), "Hide to Tray");
    let quit = CustomMenuItem::new("quit".to_string(), "Quit");

    let tray_menu = SystemTrayMenu::new()
        .add_item(show)
        .add_item(hide)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);

    let system_tray = SystemTray::new().with_menu(tray_menu);

    tauri::Builder::default()
        .manage(PythonServer(Mutex::new(None)))
        .setup(|app| {
            let app_handle = app.handle();
            
            // Start Python server
            let python_child = start_python_server(&app_handle);
            
            // Store the child process
            let state = app.state::<PythonServer>();
            *state.0.lock().unwrap() = Some(python_child);
            
            // Wait a moment for server to start, then create window
            std::thread::sleep(std::time::Duration::from_millis(1500));
            
            // Main window pointing to Python server
            WindowBuilder::new(
                app,
                "main",
                WindowUrl::External("http://localhost:8000".parse().unwrap()),
            )
            .title("Apex - Your Personal AI Assistant")
            .inner_size(960.0, 700.0)
            .min_inner_size(600.0, 500.0)
            .center()
            .decorations(true)
            .build()?;
            
            Ok(())
        })
        .system_tray(system_tray)
        .on_system_tray_event(|app, event| match event {
            SystemTrayEvent::LeftClick { .. } => {
                if let Some(window) = app.get_window("main") {
                    window.show().unwrap();
                    window.set_focus().unwrap();
                }
            }
            SystemTrayEvent::MenuItemClick { id, .. } => match id.as_str() {
                "show" => {
                    if let Some(window) = app.get_window("main") {
                        window.show().unwrap();
                        window.set_focus().unwrap();
                    }
                }
                "hide" => {
                    if let Some(window) = app.get_window("main") {
                        window.hide().unwrap();
                    }
                }
                "quit" => {
                    // Kill Python server
                    let state = app.state::<PythonServer>();
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                    std::process::exit(0);
                }
                _ => {}
            },
            _ => {}
        })
        .on_window_event(|event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event.event() {
                // Hide to tray instead of closing
                event.window().hide().unwrap();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn start_python_server(app_handle: &tauri::AppHandle) -> Child {
    // Get the path to the Python sidecar
    let resource_path = app_handle
        .path_resolver()
        .resolve_resource("server")
        .expect("failed to resolve server resource");
    
    // In development, run python directly
    #[cfg(debug_assertions)]
    {
        Command::new("python")
            .arg("server.py")
            .current_dir(resource_path.parent().unwrap().parent().unwrap())
            .spawn()
            .expect("Failed to start Python server")
    }
    
    // In production, run the bundled executable
    #[cfg(not(debug_assertions))]
    {
        Command::new(resource_path)
            .spawn()
            .expect("Failed to start server")
    }
}
