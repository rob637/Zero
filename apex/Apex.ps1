# Apex Launcher with System Tray
# Double-click this file or run: powershell -ExecutionPolicy Bypass -File Apex.ps1

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Configuration
$port = 8000
$url = "http://localhost:$port"

# Create notification icon
$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = [System.Drawing.SystemIcons]::Application
$notifyIcon.Text = "Apex - AI Assistant"
$notifyIcon.Visible = $true

# Create context menu
$contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

$openItem = New-Object System.Windows.Forms.ToolStripMenuItem
$openItem.Text = "Open Apex"
$openItem.Add_Click({ Start-Process $url })
$contextMenu.Items.Add($openItem)

$contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

$quitItem = New-Object System.Windows.Forms.ToolStripMenuItem
$quitItem.Text = "Quit"
$quitItem.Add_Click({
    $notifyIcon.Visible = $false
    if ($global:serverProcess) { 
        Stop-Process -Id $global:serverProcess.Id -Force -ErrorAction SilentlyContinue 
    }
    [System.Windows.Forms.Application]::Exit()
})
$contextMenu.Items.Add($quitItem)

$notifyIcon.ContextMenuStrip = $contextMenu

# Double-click to open
$notifyIcon.Add_DoubleClick({ Start-Process $url })

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Check for API key
if (-not $env:ANTHROPIC_API_KEY -and -not $env:OPENAI_API_KEY) {
    $notifyIcon.ShowBalloonTip(5000, "Apex", "Warning: No API key set. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.", [System.Windows.Forms.ToolTipIcon]::Warning)
}

# Start server
$notifyIcon.ShowBalloonTip(3000, "Apex", "Starting server...", [System.Windows.Forms.ToolTipIcon]::Info)

$global:serverProcess = Start-Process -FilePath "python" -ArgumentList "server.py" -WorkingDirectory $scriptDir -PassThru -WindowStyle Hidden

# Wait for server to start
Start-Sleep -Seconds 2

# Open browser
Start-Process $url

$notifyIcon.ShowBalloonTip(3000, "Apex", "Ready! Click the tray icon to open.", [System.Windows.Forms.ToolTipIcon]::Info)

# Keep running
[System.Windows.Forms.Application]::Run()

# Cleanup
$notifyIcon.Dispose()
if ($global:serverProcess) {
    Stop-Process -Id $global:serverProcess.Id -Force -ErrorAction SilentlyContinue
}
