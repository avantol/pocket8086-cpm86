# Click at a position relative to the MartyPC window's top-left corner.
param([Parameter(Mandatory)][int]$X, [Parameter(Mandatory)][int]$Y)
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W3 {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e);
  public struct RECT { public int L, T, R, B; }
}
"@
$p = Get-Process -Name martypc | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[W3]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$r = New-Object W3+RECT
[W3]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
[W3]::SetCursorPos($r.L + $X, $r.T + $Y) | Out-Null
Start-Sleep -Milliseconds 150
[W3]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 60
[W3]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 600
