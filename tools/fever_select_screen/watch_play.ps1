param([int]$Count = 480, [int]$IntervalMs = 400, [string]$Dir = "$PSScriptRoot\play")
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Win {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
[Win]::SetProcessDPIAware() | Out-Null
New-Item -ItemType Directory -Force $Dir | Out-Null
$p = Get-Process PuyoPuyoChampions -ErrorAction Stop | Select-Object -First 1
$r = New-Object Win+RECT
[Win]::GetClientRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
# left half of the screen: 1P field and its NEXT window
$crop = New-Object System.Drawing.Rectangle 0, 0, 1000, 1080
for ($i = 0; $i -lt $Count; $i++) {
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $dc = $g.GetHdc()
    [Win]::PrintWindow($p.MainWindowHandle, $dc, 3) | Out-Null
    $g.ReleaseHdc($dc)
    $g.Dispose()
    $part = $bmp.Clone($crop, $bmp.PixelFormat)
    $part.Save((Join-Path $Dir ('p{0:D4}.jpg' -f $i)), [System.Drawing.Imaging.ImageFormat]::Jpeg)
    $part.Dispose()
    Start-Sleep -Milliseconds $IntervalMs
}
"done $Count"
