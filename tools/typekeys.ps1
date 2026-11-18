# Type text into the MartyPC window, one key at a time (SendKeys syntax).
param([Parameter(Mandatory)][string[]]$Keys, [int]$DelayMs = 120, [int]$After = 3)
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W2 { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); }
"@
$p = Get-Process -Name martypc | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[W2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 500
foreach ($k in $Keys) {
    if ($k -match '^\{.*\}$' -or $k -match '^\^[a-z]$') { [System.Windows.Forms.SendKeys]::SendWait($k); Start-Sleep -Milliseconds $DelayMs; continue }
    foreach ($ch in $k.ToCharArray()) {
        $s = [string]$ch
        if ('+^%~(){}[]'.Contains($s)) { $s = '{' + $s + '}' }
        [System.Windows.Forms.SendKeys]::SendWait($s)
        Start-Sleep -Milliseconds $DelayMs
    }
}
Start-Sleep -Seconds $After
