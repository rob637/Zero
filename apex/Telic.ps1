# Telic Launcher with System Tray
# Double-click this file or run: powershell -ExecutionPolicy Bypass -File Telic.ps1

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Configuration
$port = 8000
$url = "http://127.0.0.1:$port"
$healthUrl = "$url/health"

# Create notification icon
$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = [System.Drawing.SystemIcons]::Application
$notifyIcon.Text = "Telic - AI OS"
$notifyIcon.Visible = $true

# Create context menu
$contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

$openItem = New-Object System.Windows.Forms.ToolStripMenuItem
$openItem.Text = "Open Telic"
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
    $notifyIcon.ShowBalloonTip(5000, "Telic", "Warning: No API key set. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.", [System.Windows.Forms.ToolTipIcon]::Warning)
}

# Start server
$notifyIcon.ShowBalloonTip(3000, "Telic", "Starting...", [System.Windows.Forms.ToolTipIcon]::Info)

$global:serverProcess = Start-Process -FilePath "python" -ArgumentList "server.py" -WorkingDirectory $scriptDir -PassThru -WindowStyle Hidden

# Wait for server readiness, then open browser (fallback open after timeout)
$opened = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 1
        if ($r.StatusCode -ge 200) {
            Start-Process $url
            $opened = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $opened) {
    Start-Process $url
}

$notifyIcon.ShowBalloonTip(3000, "Telic", "Ready! Click the tray icon to open.", [System.Windows.Forms.ToolTipIcon]::Info)

# Keep running
[System.Windows.Forms.Application]::Run()

# Cleanup
$notifyIcon.Dispose()
if ($global:serverProcess) {
    Stop-Process -Id $global:serverProcess.Id -Force -ErrorAction SilentlyContinue
}
