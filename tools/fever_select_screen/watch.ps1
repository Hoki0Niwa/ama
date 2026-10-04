param([int]$Count = 150, [int]$IntervalMs = 1000, [string]$Dir = "$PSScriptRoot\frames")
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
# 1P panel: style, dropset bar and name (for a 1920x1080 client area)
$crop = New-Object System.Drawing.Rectangle 1040, 180, 740, 340
for ($i = 0; $i -lt $Count; $i++) {
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $dc = $g.GetHdc()
    [Win]::PrintWindow($p.MainWindowHandle, $dc, 3) | Out-Null
    $g.ReleaseHdc($dc)
    $g.Dispose()
    $part = $bmp.Clone($crop, $bmp.PixelFormat)
    $part.Save((Join-Path $Dir ('f{0:D3}.png' -f $i)), [System.Drawing.Imaging.ImageFormat]::Png)
    $part.Dispose()
    Start-Sleep -Milliseconds $IntervalMs
}
"done $Count"
