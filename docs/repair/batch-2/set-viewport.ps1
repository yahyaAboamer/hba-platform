# Set Chrome's real CSS viewport width, for parity captures.
#
# CLAUDE.md asks for the app and the approved export compared at 1280 and 1440
# wide, and the portal at its phone size. The browser automation's own
# `resize_window` reports success and changes nothing: Chrome keeps a maximised
# window maximised, and the extension never restores it first.
#
# So the window is resized through Win32 - SW_RESTORE, which is the missing
# part, then SetWindowPos. The window is found by **class**, not by
# `MainWindowTitle`: Chrome is one process with many windows and reports only
# one title, which is whichever window happens to be foremost, so matching on
# the title picks the wrong window as soon as somebody switches tabs.
#
# This process is DPI-unaware, so its coordinates are already CSS pixels at
# this display's 125% scaling - which is why the numbers here read as the
# widths you want rather than as physical pixels.
#
#   powershell -File docs/repair/batch-2/set-viewport.ps1 -Width 1280
#   powershell -File docs/repair/batch-2/set-viewport.ps1 -Restore
#
# It prints the window width it achieved. Chrome enforces a minimum window
# width of about 500px, so a phone viewport cannot be had this way - the
# portal's own layout is the thing to check at that size, and the report says
# how that was done instead.
#
# **It resizes a real browser window somebody may be using.** `-Restore` puts
# it back to maximised, and the parity run ends with it.
param(
  [int]$Width = 0,
  [int]$Height = 900,
  [switch]$Restore
)

$sig = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Viewport {
  public delegate bool Proc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Proc p, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Rt, B; }

  public static IntPtr Browser() {
    IntPtr best = IntPtr.Zero; int widest = 0;
    EnumWindows((h, l) => {
      var cls = new StringBuilder(64); GetClassName(h, cls, 64);
      if (cls.ToString() != "Chrome_WidgetWin_1" || !IsWindowVisible(h)) return true;
      var t = new StringBuilder(512); GetWindowText(h, t, 512);
      if (!t.ToString().EndsWith("Google Chrome")) return true;
      R r; GetWindowRect(h, out r);
      int w = r.Rt - r.L;
      if (w > widest) { widest = w; best = h; }
      return true;
    }, IntPtr.Zero);
    return best;
  }

  public static int WidthOf(IntPtr h) { R r; GetWindowRect(h, out r); return r.Rt - r.L; }
}
'@
Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue

$h = [Viewport]::Browser()
if ($h -eq [IntPtr]::Zero) { Write-Error 'No visible Chrome browser window found.'; exit 1 }

if ($Restore) {
  [Viewport]::ShowWindow($h, 3) | Out-Null   # SW_MAXIMIZE
  'chrome window restored to maximised'
  exit 0
}

if ($Width -le 0) { Write-Error 'Pass -Width or -Restore.'; exit 1 }

[Viewport]::ShowWindow($h, 9) | Out-Null     # SW_RESTORE, or the width is ignored
Start-Sleep -Milliseconds 250

# Converge on the viewport width: the frame is a handful of pixels and differs
# between window states, so it is measured rather than assumed.
$frame = 14
for ($pass = 0; $pass -lt 4; $pass++) {
  [Viewport]::SetWindowPos($h, [IntPtr]::Zero, 0, 0, ($Width + $frame), $Height, 0x0004) | Out-Null
  Start-Sleep -Milliseconds 350
  $got = [Viewport]::WidthOf($h)
  $drift = $got - ($Width + $frame)
  if ($drift -eq 0) { break }
  $frame -= $drift
}
$final = [Viewport]::WidthOf($h)
"window is ${final}px wide for a ${Width}px viewport target"
