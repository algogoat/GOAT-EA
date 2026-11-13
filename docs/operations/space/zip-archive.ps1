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
#      b. each file is then removed through a handle that shuts out every other reader and writer (FileShare.Delete
#         only), hashed through that handle, and deleted only when it still equals its manifest row; a file that changed
#         in between stays, the removal stops there (the zip, which holds every file removed so far, is kept), exit 3;
#      c. the empty folders go, and one line is appended to <DestRoot>\ARCHIVE-INDEX.csv. A file that appeared after a
#         stays with its folders, exit 3.
# Exit 0 = archived (or planned with -DryRun), 2 = refused before any write, 3 = verification failed or the source changed
# (nothing of the changed source is removed).
param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$DestRoot, [string]$NeedsLive = '',
      [switch]$RemoveSource, [switch]$DryRun,
      [scriptblock]$AfterZip = $null,       # TEST HOOK ONLY (corrupt or truncate the zip, or change a source file); a production run never passes it
      [scriptblock]$BeforeRemove = $null)   # TEST HOOK ONLY (change or add a source file between 5a and 5b); a production run never passes it
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
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
  foreach ($f in $d.EnumerateFiles()) { if ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) { Refuse "$($f.FullName) is a link inside the source" }; [void]$files.Add($f) }
}
if (-not $files.Count) { Refuse "$src holds no file" }
$rows = foreach ($f in $files) { $fs = $f.OpenRead(); try { $h = Sha $fs } finally { $fs.Dispose() }
  [pscustomobject]@{ rel = $f.FullName.Substring($src.Length + 1).Replace('\', '/'); bytes = $f.Length; sha256 = $h; mtime_utc = $f.LastWriteTimeUtc.ToString('o') } }
$bytes = ($rows | Measure-Object bytes -Sum).Sum
if ($DryRun) { Say ("DRY RUN: {0} files, {1:N1} MB from {2} would go to {3}" -f @($rows).Count, ($bytes / 1MB), $src, $zip); exit 0 }
[void][IO.Directory]::CreateDirectory($dst)
$rows | Export-Csv -LiteralPath $man -NoTypeInformation -Encoding UTF8
[IO.Compression.ZipFile]::CreateFromDirectory($src, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
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
Say ("verified: {0} files, {1:N1} MB -> {2:N1} MB ({3:P0}); manifest {4}" -f @($rows).Count, ($bytes / 1MB), ($zb / 1MB), ($zb / [Math]::Max(1, $bytes)), $mh)
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
  # 5b. Each file: no other process may read or write it while it is checked (FileShare.Delete only); it is deleted only
  # when it still hashes to its manifest row, and the delete completes when this handle closes.
  $removed = 0
  foreach ($r in $rows) {
    $p = Join-Path $src ($r.rel.Replace('/', '\'))
    $fs = [IO.File]::Open($p, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Delete)
    try {
      $h = Sha $fs
      if ($h -ne $r.sha256) { Say ("SOURCE CHANGED during the removal: {0}; it stays; {1} of {2} files were removed (the zip and its manifest hold them and are kept)" -f $r.rel, $removed, @($rows).Count); exit 3 }
      [IO.File]::Delete($p); $removed++
    } finally { $fs.Dispose() }
  }
  # 5c. Only empty folders go: a file that appeared after 5a keeps its folder (Remove-Item without -Recurse refuses a non-empty one).
  $left = @(Get-ChildItem -LiteralPath $src -Recurse -File -Force)
  if ($left.Count) { Say ("{0} file(s) appeared in the source after the check ({1}); they stay; the {2} archived files were removed" -f $left.Count, (($left | Select-Object -First 3 | ForEach-Object { $_.FullName.Substring($src.Length + 1) }) -join '; '), $removed); exit 3 }
  Get-ChildItem -LiteralPath $src -Recurse -Directory | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
  Remove-Item -LiteralPath $src -Force
  $idx = Join-Path $dst 'ARCHIVE-INDEX.csv'; $line = [pscustomobject]@{ archived_utc = [DateTime]::UtcNow.ToString('o'); source = $src; zip = $zip; files = @($rows).Count; bytes = $bytes; zip_bytes = $zb; manifest_sha256 = $mh }
  if (Test-Path -LiteralPath $idx) { $line | Export-Csv -LiteralPath $idx -Append -NoTypeInformation -Encoding UTF8 } else { $line | Export-Csv -LiteralPath $idx -NoTypeInformation -Encoding UTF8 }
  Say "source removed after every file matched; indexed in $idx"
}
exit 0
