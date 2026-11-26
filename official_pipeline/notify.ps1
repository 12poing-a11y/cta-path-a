param([string]$Title = "CTA official pipeline", [string]$Text = "")
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.SystemIcons]::Warning
$icon.BalloonTipTitle = $Title
$icon.BalloonTipText = $Text
$icon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Warning
$icon.Visible = $true
$icon.ShowBalloonTip(10000)
Start-Sleep -Seconds 6
$icon.Dispose()
