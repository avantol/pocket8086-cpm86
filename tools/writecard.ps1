# Write build\cpm.img to a removable card, raw, and verify it.
# Must run elevated.  Usage:
#   writecard.ps1 -DiskNumber 1 [-Image ..\build\cpm.img] [-ExpectedSize 4030464]
param(
    [Parameter(Mandatory)][int]$DiskNumber,
    [string]$Image = "$PSScriptRoot\..\build\cpm.img",
    [long]$ExpectedSize = 0,
    [string]$Log = "$PSScriptRoot\..\build\writecard.log"
)
$ErrorActionPreference = 'Stop'
Start-Transcript -Path $Log -Force | Out-Null
try {
    try { Update-HostStorageCache } catch {}
    $disk = Get-Disk | Where-Object Number -eq $DiskNumber
    if (-not $disk) {
        "Get-Disk did not list disk $DiskNumber; using WMI"
        $w = Get-CimInstance Win32_DiskDrive | Where-Object Index -eq $DiskNumber
        if (-not $w) { throw "disk $DiskNumber not found" }
        $disk = [pscustomobject]@{ FriendlyName = $w.Model; BusType = $w.InterfaceType;
            Size = [long]$w.Size; IsSystem = $false; IsBoot = $false; Wmi = $true }
        "WMI: $($w.Model) $($w.InterfaceType) $($w.MediaType) $($w.Size)"
        if ($w.MediaType -notmatch 'Removable') { throw "refusing: not removable media" }
        $disk.BusType = 'USB'
    }
    $img = [IO.File]::ReadAllBytes((Resolve-Path $Image))
    "Disk $DiskNumber : $($disk.FriendlyName)  bus=$($disk.BusType)  size=$($disk.Size)  system=$($disk.IsSystem) boot=$($disk.IsBoot)"
    "Image: $Image  ($($img.Length) bytes)"
    if ($disk.BusType -ne 'USB' -and $disk.BusType -ne 'SD') { throw "refusing: disk is not USB/SD" }
    if ($disk.IsSystem -or $disk.IsBoot) { throw "refusing: system/boot disk" }
    if ($disk.Size -gt 64GB) { throw "refusing: disk larger than 64 GB" }
    if ($ExpectedSize -and $disk.Size -ne $ExpectedSize) { throw "refusing: size $($disk.Size) != expected $ExpectedSize" }
    if ($img.Length -gt $disk.Size) { throw "image larger than disk" }
    if ($img.Length % 512) { throw "image not a whole number of sectors" }

    Add-Type @"
using System; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
public static class Vol {
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern SafeFileHandle CreateFile(string n, uint a, uint s, IntPtr sa, uint c, uint f, IntPtr t);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr i, uint il, IntPtr o, uint ol, out uint r, IntPtr ov);
  public static SafeFileHandle LockDismount(string letter) {
    var h = CreateFile(@"\\.\" + letter + ":", 0xC0000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
    if (h.IsInvalid) throw new Exception("open volume failed " + Marshal.GetLastWin32Error());
    uint r;
    if (!DeviceIoControl(h, 0x00090018, IntPtr.Zero, 0, IntPtr.Zero, 0, out r, IntPtr.Zero))
      throw new Exception("lock volume failed " + Marshal.GetLastWin32Error());
    if (!DeviceIoControl(h, 0x00090020, IntPtr.Zero, 0, IntPtr.Zero, 0, out r, IntPtr.Zero))
      throw new Exception("dismount volume failed " + Marshal.GetLastWin32Error());
    return h;
  }
}
"@
    $locks = @()
    $letters = @(Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue |
                 Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter })
    if (-not $letters) { $letters = @('D') ; "No partition info; assuming D:" }
    foreach ($L in $letters) { "Locking and dismounting ${L}:"; $locks += [Vol]::LockDismount($L) }
    $path = "\\.\PhysicalDrive$DiskNumber"
    $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    $chunk = 64KB
    for ($o = 0; $o -lt $img.Length; $o += $chunk) {
        $n = [Math]::Min($chunk, $img.Length - $o)
        $fs.Write($img, $o, $n)
    }
    $fs.Flush()
    $fs.Close()
    "Wrote $($img.Length) bytes. Verifying..."
    $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    $buf = New-Object byte[] $img.Length
    $got = 0
    while ($got -lt $img.Length) {
        $r = $fs.Read($buf, $got, [Math]::Min($chunk, $img.Length - $got))
        if ($r -le 0) { break }
        $got += $r
    }
    $fs.Close()
    $bad = 0
    for ($i = 0; $i -lt $img.Length; $i++) { if ($buf[$i] -ne $img[$i]) { $bad++ } }
    if ($bad) { "VERIFY FAILED: $bad bytes differ" } else { "VERIFY OK" }
}
catch { "ERROR: $($_.Exception.Message)" }
finally {
    foreach ($h in $locks) { try { $h.Close() } catch {} }
    try { Update-HostStorageCache } catch {}
    Stop-Transcript | Out-Null
}
