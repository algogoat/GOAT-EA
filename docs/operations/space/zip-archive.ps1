# Ops 2026-11-13: archive ONE folder as a zip by the per-file method (Claude-Mac goatai#2750 6845747846, 6846197081; Vince:
# "Ops needs to smartly manage space there"). Research run folders are 99% CSV and zip to about 10% (measured 6846190790).
#
#   1. refuse: a source or destination on E: or F: (Vince's own drives); a source on the needs-live list (or inside, or
#      containing, a listed path); a source holding a junction or symlink; an existing zip (create-only); an empty source
#   2. hash every source file (SHA-256) into a manifest
#   3. zip to <DestRoot>\<leaf>.zip, the manifest beside it as <leaf>.zip.manifest.csv
#   4. open the zip and hash every entry; the entry set must equal the manifest and every hash must match; on any mismatch
#      the bad zip is deleted, the source is left untouched, exit 3
#   5. only with -RemoveSource (Codex on #332: a source written after the zip must never be deleted):
#      a. every source file is hashed again; any file that changed, went missing or appeared since the manifest deletes
#         the zip, removes nothing, exit 3;
#      b. each file is opened with read and delete rights and no sharing at all (nobody else can read, write, rename or
#         replace it meanwhile), hashed through that handle, and deleted THROUGH THAT HANDLE (never by path) only when it
#         still equals its manifest row; a file that changed stays, the removal stops there (the zip, which holds every
#         file removed so far, is kept; the index gets a 'partial' row), exit 3;
#      c. the empty folders go, and a 'complete' row is appended to <DestRoot>\ARCHIVE-INDEX.csv. A file that appeared
#         after a stays with its folders ('partial' row), exit 3.
#   A manifest or zip that fails while being written (disk full, an unreadable file) is removed by the run, exit 3.
# Exit 0 = archived (or planned with -DryRun), 2 = refused before any write, 3 = verification failed or the source changed
# (nothing of the changed source is removed).
param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$DestRoot, [string]$NeedsLive = '',
      [switch]$RemoveSource, [switch]$DryRun,
      [scriptblock]$AfterZip = $null,       # TEST HOOK ONLY (corrupt or truncate the zip, or change a source file); a production run never passes it
      [scriptblock]$BeforeRemove = $null,   # TEST HOOK ONLY (change or add a source file between 5a and 5b); a production run never passes it
      [scriptblock]$BeforeZip = $null,      # TEST HOOK ONLY (make the zip's creation fail after the manifest is written)
      [scriptblock]$DuringRemove = $null,   # TEST HOOK ONLY (try to rename or replace a file while 5b holds it)
      [scriptblock]$AfterCheck = $null)     # TEST HOOK ONLY (another run takes the same zip and manifest names after the create-only check)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
# Codex on #332 (P1, 4562087122): a verified file is deleted through the very handle it was hashed through, never by path, so
# a rename-and-replace at that path can never redirect the delete. SetFileInformationByHandle(FileDispositionInfo) marks the
# handle's own file; it goes when the handle closes.
if (-not ('ZipArchiveNative2' -as [type])) {
  Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
public static class ZipArchiveNative2 {
  [StructLayout(LayoutKind.Sequential)] struct FileDispositionInfo { [MarshalAs(UnmanagedType.U1)] public bool DeleteFile; }
  [StructLayout(LayoutKind.Sequential)] struct FileDispositionInfoEx { public uint Flags; }
  [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetFileInformationByHandle(SafeFileHandle h, int infoClass, ref FileDispositionInfo info, int size);
  [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetFileInformationByHandle(SafeFileHandle h, int infoClass, ref FileDispositionInfoEx info, int size);
  // Claude-Mac on #332 (6850291527): a read-only file refused the plain disposition. FileDispositionInfoEx (class 21) with
  // DELETE (0x1) | IGNORE_READONLY_ATTRIBUTE (0x10) deletes it through the same handle without changing its attribute by path.
  // Windows before 10 1809 has no class 21 (ERROR_INVALID_PARAMETER): the plain disposition is used there.
  public static void DeleteByHandle(SafeFileHandle h) {
    FileDispositionInfoEx x = new FileDispositionInfoEx(); x.Flags = 0x1 | 0x10;
    if (SetFileInformationByHandle(h, 21, ref x, Marshal.SizeOf(typeof(FileDispositionInfoEx)))) return;
    int err = Marshal.GetLastWin32Error();
    if (err != 87 && err != 1 && err != 50) throw new System.ComponentModel.Win32Exception(err);
    FileDispositionInfo i = new FileDispositionInfo(); i.DeleteFile = true;
    if (!SetFileInformationByHandle(h, 4, ref i, Marshal.SizeOf(typeof(FileDispositionInfo)))) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  }
}
'@
}
# Codex on #332 (P2 4562628146): the zip holds and verifies only a file's unnamed data stream, and the handle delete removes
# every stream, so a named NTFS stream would be lost with no archived copy. As the product's run-folder archiver
# (controller/studio_run_folder_archive.alternate_streams), a source holding one is refused; FindFirstStreamW needs only
# attribute access, so it also reads a file that 5b holds with no sharing.
if (-not ('ZipArchiveStreams' -as [type])) {
  Add-Type -TypeDefinition @'
using System; using System.ComponentModel; using System.Runtime.InteropServices;
public static class ZipArchiveStreams {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct FindStreamData { public long StreamSize; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 296)] public string Name; }
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr FindFirstStreamW(string path, int level, out FindStreamData data, uint flags);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool FindNextStreamW(IntPtr h, out FindStreamData data);
  [DllImport("kernel32.dll")] static extern bool FindClose(IntPtr h);
  // The first stream name other than ::$DATA, or null when the file has none.
  public static string FirstNamed(string path) {
    if (path.Length >= 248 && !path.StartsWith(@"\\?\")) path = @"\\?\" + path;
    FindStreamData d; IntPtr h = FindFirstStreamW(path, 0, out d, 0);
    if (h == new IntPtr(-1)) { int e = Marshal.GetLastWin32Error(); if (e == 38) return null; throw new Win32Exception(e, "FindFirstStreamW " + path); }
    try { do { if (!string.Equals(d.Name, "::$DATA", StringComparison.OrdinalIgnoreCase)) return d.Name; } while (FindNextStreamW(h, out d)); return null; } finally { FindClose(h); }
  }
}
'@
}
function Say($m) { '{0:yyyy-MM-ddTHH:mm:ss}Z ZIP-ARCHIVE: {1}' -f [DateTime]::UtcNow, $m }
function Refuse($m) { Say "REFUSED: $m"; exit 2 }
function Sha([IO.Stream]$s) { $h = [Security.Cryptography.SHA256]::Create(); try { ([BitConverter]::ToString($h.ComputeHash($s)) -replace '-', '').ToLower() } finally { $h.Dispose() } }
$src = [IO.Path]::GetFullPath($Source).TrimEnd('\'); $dst = [IO.Path]::GetFullPath($DestRoot).TrimEnd('\')
foreach ($p in $src, $dst) { if ($p -match '^[EeFf]:') { Refuse "$p is on E: or F:, which are Vince's own drives" } }
if (-not (Test-Path -LiteralPath $src -PathType Container)) { Refuse "no source folder $src" }
if ($RemoveSource -and -not $NeedsLive) { Refuse '-RemoveSource needs -NeedsLive (the list of folders that must stay live)' }
# Claude-Mac on #332: a junction or symlink as the source or destination root, or anywhere above them, would let a removal
# reach real files on another volume through the link, and would make the E:/F: check read the link's path, not the
# target's. So no folder in either chain may be a reparse point; with none, the path checked above is the real location.
foreach ($p in $src, $dst) {
  $cur = $p
  while ($cur -and $cur.Length -gt 3) {
    if (Test-Path -LiteralPath $cur) { $it = Get-Item -LiteralPath $cur -Force; if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { Refuse "$cur is a junction or symlink (on the path to $p); point at the real folder instead" } }
    $cur = Split-Path $cur -Parent
  }
}
if ($NeedsLive) {
  if (-not (Test-Path -LiteralPath $NeedsLive)) { Refuse "the needs-live list $NeedsLive cannot be read" }
  foreach ($l in (Get-Content -LiteralPath $NeedsLive | Where-Object { $_.Trim() -and -not $_.StartsWith('#') })) {
    $n = [IO.Path]::GetFullPath($l.Trim()).TrimEnd('\')
    if ($src -ieq $n -or $src.StartsWith($n + '\', 'OrdinalIgnoreCase') -or $n.StartsWith($src + '\', 'OrdinalIgnoreCase')) { Refuse "$src is needed live ($n on $NeedsLive)" }
  }
}
$leaf = Split-Path $src -Leaf; $zip = Join-Path $dst "$leaf.zip"; $man = "$zip.manifest.csv"
if ((Test-Path -LiteralPath $zip) -or (Test-Path -LiteralPath $man)) { Refuse "$zip or its manifest exists (create-only)" }
$files = New-Object Collections.ArrayList; $stack = New-Object Collections.Stack; $stack.Push((New-Object IO.DirectoryInfo $src))
while ($stack.Count) {
  $d = $stack.Pop()
  foreach ($s in $d.EnumerateDirectories()) { if ($s.Attributes -band [IO.FileAttributes]::ReparsePoint) { Refuse "$($s.FullName) is a junction or symlink inside the source" }; $stack.Push($s) }
  foreach ($f in $d.EnumerateFiles()) { if ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) { Refuse "$($f.FullName) is a link inside the source" }
    $ns = [ZipArchiveStreams]::FirstNamed($f.FullName); if ($ns) { Refuse "$($f.FullName) has the NTFS stream $ns, which the zip would not hold and the removal would destroy" }
    [void]$files.Add($f) }
}
if (-not $files.Count) { Refuse "$src holds no file" }
$rows = foreach ($f in $files) { $fs = $f.OpenRead(); try { $h = Sha $fs } finally { $fs.Dispose() }
  [pscustomobject]@{ rel = $f.FullName.Substring($src.Length + 1).Replace('\', '/'); bytes = $f.Length; sha256 = $h; mtime_utc = $f.LastWriteTimeUtc.ToString('o') } }
$bytes = ($rows | Measure-Object bytes -Sum).Sum
if ($DryRun) { Say ("DRY RUN: {0} files, {1:N1} MB from {2} would go to {3}" -f @($rows).Count, ($bytes / 1MB), $src, $zip); exit 0 }
[void][IO.Directory]::CreateDirectory($dst)
# Codex on #332 (P1 4562193968): two runs with the same destination and folder name could both pass the check above, and the
# second one's cleanup could delete the first one's verified zip. The manifest is now created with CreateNew, atomically: the
# run that creates it owns the pair, and any other run refuses there (exit 2) without touching it. The zip is built under a
# unique temporary name and moved into place (the move refuses an existing zip).
# Codex on #332 (P2 4562087134): a manifest or zip that fails half-way (disk full, an unreadable source file) is removed by
# this run, but only what this run itself created, so a retry is not refused and no partial file keeps disk space.
$ownMan = $false; $ownZip = $false; $tmp = Join-Path $dst ("$leaf.zip." + [Guid]::NewGuid().ToString('N') + '.partial')
if ($AfterCheck) { & $AfterCheck $src }
try {
  $mfs = $null; try { $mfs = New-Object IO.FileStream($man, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None) } catch { $mfs = $null }
  if (-not $mfs) { Refuse "$man was created by another run after the create-only check; nothing of it was touched" }
  $ownMan = $true
  $sw = New-Object IO.StreamWriter($mfs, (New-Object Text.UTF8Encoding($true)))
  try { foreach ($line in ($rows | ConvertTo-Csv -NoTypeInformation)) { $sw.WriteLine($line) } } finally { $sw.Dispose() }
  if ($BeforeZip) { & $BeforeZip $src }
  [IO.Compression.ZipFile]::CreateFromDirectory($src, $tmp, [IO.Compression.CompressionLevel]::Optimal, $false)
  [IO.File]::Move($tmp, $zip); $ownZip = $true
} catch {
  Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  if ($ownZip) { Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue }
  if ($ownMan) { Remove-Item -LiteralPath $man -Force -ErrorAction SilentlyContinue }
  Say ("ZIP FAILED: {0}; only what this run created was removed, the source is untouched" -f $_.Exception.Message); exit 3
}
if ($AfterZip) { & $AfterZip $zip }
$want = @{}; foreach ($r in $rows) { $want[$r.rel] = $r.sha256 }
$bad = New-Object Collections.ArrayList; $seen = @{}
try {
  $z = [IO.Compression.ZipFile]::OpenRead($zip)
  try { foreach ($e in $z.Entries) { if ($e.FullName.EndsWith('/')) { continue }; $k = $e.FullName.Replace('\', '/'); $seen[$k] = 1
          $st = $e.Open(); try { $h = Sha $st } finally { $st.Dispose() }
          if (-not $want.ContainsKey($k)) { [void]$bad.Add("extra entry $k") } elseif ($want[$k] -ne $h) { [void]$bad.Add("hash mismatch $k") } } }
  finally { $z.Dispose() }
} catch { [void]$bad.Add("the zip cannot be read: $($_.Exception.Message)") }
foreach ($k in $want.Keys) { if (-not $seen.ContainsKey($k)) { [void]$bad.Add("missing entry $k") } }
if ($bad.Count) { Remove-Item -LiteralPath $zip, $man -Force -ErrorAction SilentlyContinue; Say ("VERIFY FAILED ({0}): {1}; the zip was deleted, the source is untouched" -f $bad.Count, (($bad | Select-Object -First 3) -join '; ')); exit 3 }
$zb = (Get-Item -LiteralPath $zip).Length; $mh = (Get-FileHash -LiteralPath $man -Algorithm SHA256).Hash.ToLower()
Say ("verified: {0} files, {1:N1} MB -> {2:N1} MB ({3:P0}); manifest {4}" -f @($rows).Count, ($bytes / 1MB), ($zb / 1MB), ($zb / [Math]::Max([double]1, [double]$bytes)), $mh)
if ($RemoveSource) {
  # 5a. The source as it is now must still be exactly the manifest (Codex on #332: the zip proves only the bytes read then).
  $now = @{}; $st2 = New-Object Collections.Stack; $st2.Push((New-Object IO.DirectoryInfo $src))
  while ($st2.Count) { $d = $st2.Pop(); foreach ($s in $d.EnumerateDirectories()) { $st2.Push($s) }; foreach ($f in $d.EnumerateFiles()) { $now[$f.FullName.Substring($src.Length + 1).Replace('\', '/')] = $f } }
  $changed = New-Object Collections.ArrayList
  foreach ($r in $rows) {
    if (-not $now.ContainsKey($r.rel)) { [void]$changed.Add("missing $($r.rel)"); continue }
    $fs = $now[$r.rel].OpenRead(); try { $h = Sha $fs } finally { $fs.Dispose() }
    if ($h -ne $r.sha256) { [void]$changed.Add("changed $($r.rel)") }
  }
  foreach ($k in $now.Keys) { if (-not $want.ContainsKey($k)) { [void]$changed.Add("new $k") } }
  if ($changed.Count) { Remove-Item -LiteralPath $zip, $man -Force -ErrorAction SilentlyContinue; Say ("SOURCE CHANGED after the zip ({0}): {1}; the zip was deleted, nothing was removed" -f $changed.Count, (($changed | Select-Object -First 3) -join '; ')); exit 3 }
  if ($BeforeRemove) { & $BeforeRemove $src }
  # One index row per run that removed anything: status complete, or partial when 5b stopped part-way (Claude-Mac on #332).
  $idx = Join-Path $dst 'ARCHIVE-INDEX.csv'
  function Write-IndexRow([string]$status, [int]$removedCount) {
    $line = [pscustomobject]@{ archived_utc = [DateTime]::UtcNow.ToString('o'); status = $status; source = $src; zip = $zip; files = @($rows).Count; files_removed = $removedCount; bytes = $bytes; zip_bytes = $zb; manifest_sha256 = $mh }
    if (Test-Path -LiteralPath $idx) { $line | Export-Csv -LiteralPath $idx -Append -NoTypeInformation -Encoding UTF8 } else { $line | Export-Csv -LiteralPath $idx -NoTypeInformation -Encoding UTF8 }
  }
  # 5b. Each file is opened with read and delete rights and NO sharing: no other process can read, write, rename or replace
  # it while it is checked. It is hashed through that handle and, only if it still matches its manifest row, deleted through
  # that same handle (Codex P1 4562087122: never by path).
  $removed = 0
  $rights = [Security.AccessControl.FileSystemRights]::Read -bor [Security.AccessControl.FileSystemRights]::Delete
  foreach ($r in $rows) {
    $p = Join-Path $src ($r.rel.Replace('/', '\'))
    # Claude-Mac on #332 (6850291527): ANY failure here (the open, the hash, the delete) stops the removal with the
    # partial row written, never as a bare throw past the index.
    $fail = $null; $changedNow = $false
    try {
      $fs = New-Object IO.FileStream($p, [IO.FileMode]::Open, $rights, [IO.FileShare]::None, 65536, [IO.FileOptions]::None)
      try {
        $h = Sha $fs
        if ($DuringRemove) { & $DuringRemove $p }
        if ($h -ne $r.sha256 -or [ZipArchiveStreams]::FirstNamed($p)) { $changedNow = $true } else { [ZipArchiveNative2]::DeleteByHandle($fs.SafeFileHandle); $removed++ }   # a named stream added since the check counts as a change
      } finally { $fs.Dispose() }
    } catch { $fail = $_.Exception.Message }
    if ($changedNow -or $fail) {
      if ($removed) { Write-IndexRow 'partial' $removed }
      $why = if ($changedNow) { 'SOURCE CHANGED during the removal' } else { "REMOVAL FAILED ($fail)" }
      Say ("{0}: {1}; it stays; {2} of {3} files were removed (the zip and its manifest hold them and are kept{4})" -f $why, $r.rel, $removed, @($rows).Count, $(if ($removed) { "; index row 'partial' in $idx" } else { '' })); exit 3
    }
  }
  # 5c. Only empty folders go: a file that appeared after 5a keeps its folder (Remove-Item without -Recurse refuses a non-empty one).
  $left = @(Get-ChildItem -LiteralPath $src -Recurse -File -Force)
  if ($left.Count) { Write-IndexRow 'partial' $removed; Say ("{0} file(s) appeared in the source after the check ({1}); they stay; the {2} archived files were removed; index row 'partial'" -f $left.Count, (($left | Select-Object -First 3 | ForEach-Object { $_.FullName.Substring($src.Length + 1) }) -join '; '), $removed); exit 3 }
  # Codex on #332 (P2 4562193985): -Force includes hidden and system folders, so the bottom-up removal empties the tree and
  # the root's non-recursive removal never meets a folder it would prompt for.
  Get-ChildItem -LiteralPath $src -Recurse -Directory -Force | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
  Remove-Item -LiteralPath $src -Force
  Write-IndexRow 'complete' $removed
  Say "source removed after every file matched; indexed in $idx"
}
exit 0
