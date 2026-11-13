# Ops 2026-11-13: tests of zip-archive.ps1 on fixture folders in TEMP (no live folder, nothing on E: or F: is written).
# Exit 0 = all pass.
param([string]$Work = (Join-Path $env:TEMP ("zip-archive-test-" + [Guid]::NewGuid().ToString('N'))))
$ErrorActionPreference = 'Stop'
$tool = Join-Path (Split-Path $MyInvocation.MyCommand.Path) 'zip-archive.ps1'
$null = New-Item -ItemType Directory -Path $Work -Force
$fail = 0
function Check([string]$name, [bool]$ok, $got) { if ($ok) { "PASS  $name" } else { "FAIL  $name  -> $got"; $script:fail++ } }
function Fixture([string]$name) {
  $d = Join-Path $Work $name; $null = New-Item -ItemType Directory -Path (Join-Path $d 'deploy\EURUSD') -Force
  $rng = New-Object Random 7
  $csv = (1..4000 | ForEach-Object { '2026.10.0{0} 10:{1:D2},{2},{3}' -f ($_ % 9 + 1), ($_ % 60), (1.1 + $rng.NextDouble() / 100), $_ }) -join "`r`n"
  [IO.File]::WriteAllText((Join-Path $d 'equity.csv'), $csv); [IO.File]::WriteAllText((Join-Path $d 'deploy\EURUSD\GOAT V1.49 EURUSD.set'), "Lots=0.1`r`nMode=2`r`n")
  $b = New-Object byte[] 3000; $rng.NextBytes($b); [IO.File]::WriteAllBytes((Join-Path $d 'deploy\blob.bin'), $b)
  return $d
}
function Run([hashtable]$a) {   # a tool that throws (not an exit code) counts as code 99, so the remaining cases still run
  $ErrorActionPreference = 'Continue'; $global:LASTEXITCODE = 0
  try { $o = & $tool @a 2>&1 | ForEach-Object { "$_" }; $c = $LASTEXITCODE } catch { $o = @("THREW: $($_.Exception.Message)"); $c = 99 }
  @{ code = $c; out = ($o -join ' ') }
}
$dest = Join-Path $Work 'archive'
# 1. Happy path with -RemoveSource: verified, source gone, zip and manifest present, index row written, every file round-trips.
$s1 = Fixture 'R111111111111'; $before = @{}; foreach ($f in Get-ChildItem $s1 -Recurse -File) { $before[$f.FullName.Substring($s1.Length + 1)] = (Get-FileHash $f.FullName).Hash }
$nlEmpty = Join-Path $Work 'needs-live-empty.txt'; [IO.File]::WriteAllText($nlEmpty, "# nothing needed live in the fixtures
")
$r = Run @{ Source = $s1; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty }
$z = Join-Path $dest 'R111111111111.zip'
Check 'archives, verifies and removes the source' ($r.code -eq 0 -and $r.out -match 'verified: 3 files' -and -not (Test-Path $s1) -and (Test-Path $z) -and (Test-Path "$z.manifest.csv") -and (Test-Path (Join-Path $dest 'ARCHIVE-INDEX.csv'))) $r.out
$x = Join-Path $Work 'unzipped'; [IO.Compression.ZipFile]::ExtractToDirectory($z, $x)
$same = $true; foreach ($k in $before.Keys) { if ((Get-FileHash (Join-Path $x $k)).Hash -ne $before[$k]) { $same = $false } }
Check 'every file round-trips byte for byte' ($same -and @(Get-ChildItem $x -Recurse -File).Count -eq 3) "same=$same"
# 2. Corrupted member: bytes flipped in the middle of the zip after it is written: verification fails, source untouched.
$s2 = Fixture 'R222222222222'
$corrupt = { param($zp) $b = [IO.File]::ReadAllBytes($zp); for ($i = 60; $i -lt 400; $i++) { $b[$i] = $b[$i] -bxor 0x5A }; [IO.File]::WriteAllBytes($zp, $b) }
$r = Run @{ Source = $s2; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; AfterZip = $corrupt }
Check 'a corrupted member stops it; source untouched; bad zip deleted' ($r.code -eq 3 -and $r.out -match 'VERIFY FAILED' -and @(Get-ChildItem $s2 -Recurse -File).Count -eq 3 -and -not (Test-Path (Join-Path $dest 'R222222222222.zip'))) $r.out
# 3. Short write: the zip truncated to half: verification fails, source untouched.
$s3 = Fixture 'R333333333333'
$short = { param($zp) $b = [IO.File]::ReadAllBytes($zp); [IO.File]::WriteAllBytes($zp, $b[0..([int]($b.Length / 2))]) }
$r = Run @{ Source = $s3; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; AfterZip = $short }
Check 'a short write stops it; source untouched' ($r.code -eq 3 -and @(Get-ChildItem $s3 -Recurse -File).Count -eq 3) $r.out
# 4. A missing entry (an entry deleted from the zip): stops it.
$s4 = Fixture 'R444444444444'
$drop = { param($zp) $za = [IO.Compression.ZipFile]::Open($zp, 'Update'); try { ($za.Entries | Where-Object { $_.FullName -like '*blob.bin' }).Delete() } finally { $za.Dispose() } }
$r = Run @{ Source = $s4; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; AfterZip = $drop }
Check 'a missing entry stops it; source untouched' ($r.code -eq 3 -and $r.out -match 'missing entry' -and (Test-Path (Join-Path $s4 'deploy\blob.bin'))) $r.out
# 5-6. E: and F: are refused before any work, as source or destination.
$r = Run @{ Source = $s4; DestRoot = 'E:\GOAT-zip-test' }; Check 'E: as destination is refused' ($r.code -eq 2 -and $r.out -match "Vince's own drives") $r.out
$r = Run @{ Source = 'F:\anything'; DestRoot = $dest }; Check 'F: as source is refused' ($r.code -eq 2 -and $r.out -match "Vince's own drives") $r.out
# 7. The needs-live list: the source itself, a folder inside it, or a parent of it on the list refuses.
$nl = Join-Path $Work 'needs-live.txt'; [IO.File]::WriteAllText($nl, "# needs live`r`n$(Join-Path $s4 'deploy\EURUSD')`r`n")
$r = Run @{ Source = $s4; DestRoot = $dest; NeedsLive = $nl }; Check 'a needed-live path inside the source refuses' ($r.code -eq 2 -and $r.out -match 'needed live') $r.out
[IO.File]::WriteAllText($nl, "$Work`r`n"); $r = Run @{ Source = $s4; DestRoot = $dest; NeedsLive = $nl }; Check 'a needed-live parent refuses' ($r.code -eq 2) $r.out
# 8. Create-only: an existing zip refuses.
$s8 = Fixture 'R111111111111'; $r = Run @{ Source = $s8; DestRoot = $dest }; Check 'an existing zip refuses (create-only)' ($r.code -eq 2 -and $r.out -match 'create-only') $r.out
# 9. A junction inside the source refuses (the zip would follow it).
$s9 = Fixture 'R999999999999'; $null = New-Item -ItemType Junction -Path (Join-Path $s9 'link') -Target (Join-Path $Work 'unzipped')
$r = Run @{ Source = $s9; DestRoot = $dest }; Check 'a junction inside the source refuses' ($r.code -eq 2 -and $r.out -match 'junction') $r.out
cmd /c "rmdir `"$(Join-Path $s9 'link')`""
# 10. An empty source refuses; a dry run writes nothing.
$s10 = Join-Path $Work 'Rempty0000000'; $null = New-Item -ItemType Directory -Path $s10
$r = Run @{ Source = $s10; DestRoot = $dest }; Check 'an empty source refuses' ($r.code -eq 2) $r.out
$r = Run @{ Source = $s4; DestRoot = (Join-Path $Work 'dry'); DryRun = $true }; Check 'a dry run writes nothing' ($r.code -eq 0 -and $r.out -match 'DRY RUN: 3 files' -and -not (Test-Path (Join-Path $Work 'dry'))) $r.out
# 11. -RemoveSource without -NeedsLive refuses (Claude-Mac on #332).
$s11 = Fixture 'Rb11111111111'; $r = Run @{ Source = $s11; DestRoot = $dest; RemoveSource = $true }
Check '-RemoveSource without -NeedsLive refuses' ($r.code -eq 2 -and $r.out -match 'needs -NeedsLive' -and @(Get-ChildItem $s11 -Recurse -File).Count -eq 3) $r.out
# 12-14. A junction as the source root, as the destination root, or above the source refuses; the real files behind it stay.
$real = Fixture 'Rreal00000000'; $j = Join-Path $Work 'Rjunc00000000'; $null = New-Item -ItemType Junction -Path $j -Target $real
$r = Run @{ Source = $j; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty }
Check 'a junction as the source root refuses; its target untouched' ($r.code -eq 2 -and $r.out -match 'junction or symlink' -and @(Get-ChildItem $real -Recurse -File).Count -eq 3) $r.out
$dj = Join-Path $Work 'destjunc'; $null = New-Item -ItemType Junction -Path $dj -Target $dest
$r = Run @{ Source = $real; DestRoot = $dj }; Check 'a junction as the destination root refuses' ($r.code -eq 2 -and $r.out -match 'junction or symlink') $r.out
$parentReal = Join-Path $Work 'parentreal'; $null = New-Item -ItemType Directory -Path $parentReal; $null = Copy-Item -Recurse $real (Join-Path $parentReal 'Rinner0000000')
$pj = Join-Path $Work 'parentjunc'; $null = New-Item -ItemType Junction -Path $pj -Target $parentReal
$r = Run @{ Source = (Join-Path $pj 'Rinner0000000'); DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty }
Check 'a junction above the source refuses; the real files stay' ($r.code -eq 2 -and $r.out -match 'junction or symlink' -and @(Get-ChildItem (Join-Path $parentReal 'Rinner0000000') -Recurse -File).Count -eq 3) $r.out
foreach ($x in $j, $dj, $pj) { cmd /c "rmdir `"$x`"" }
# 15-17 (Codex on #332, P1): a source written after the zip is never deleted.
# 15. A source file changed between the zip and the removal (the zip itself verifies): nothing removed, the new bytes stay,
#     the zip is deleted.
$s15 = Fixture 'Rc15000000000'; $edit = { param($zp) [IO.File]::AppendAllText((Join-Path $s15 'equity.csv'), "`r`nlate row") }
$r = Run @{ Source = $s15; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; AfterZip = $edit }
Check 'a source changed after the zip: nothing removed, the new bytes stay, the zip is deleted' ($r.code -eq 3 -and $r.out -match 'SOURCE CHANGED after the zip' -and @(Get-ChildItem $s15 -Recurse -File).Count -eq 3 -and ([IO.File]::ReadAllText((Join-Path $s15 'equity.csv'))).EndsWith('late row') -and -not (Test-Path (Join-Path $dest 'Rc15000000000.zip'))) $r.out
# 16. A source file changed after that check, during the removal: that file stays with its new bytes; the zip (which holds
#     what was removed) is kept.
$s16 = Fixture 'Rc16000000000'; $late = { param($sp) [IO.File]::AppendAllText((Join-Path $sp 'deploy\blob.bin'), 'x') }
$r = Run @{ Source = $s16; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; BeforeRemove = $late }
Check 'a source changed during the removal: it stays with its new bytes; the zip is kept' ($r.code -eq 3 -and $r.out -match 'SOURCE CHANGED during the removal' -and (Test-Path (Join-Path $s16 'deploy\blob.bin')) -and (Get-Item (Join-Path $s16 'deploy\blob.bin')).Length -eq 3001 -and (Test-Path (Join-Path $dest 'Rc16000000000.zip'))) $r.out
$p16 = @(Import-Csv (Join-Path $dest 'ARCHIVE-INDEX.csv') | Where-Object { $_.source -eq $s16 })
Check 'a removal that stopped part-way has a partial index row' ($p16.Count -eq 1 -and $p16[0].status -eq 'partial' -and [int]$p16[0].files_removed -ge 1 -and [int]$p16[0].files_removed -lt 3) ($p16 | ConvertTo-Json -Compress)
# 17. A file that appears in the source after the check stays, with its folder.
$s17 = Fixture 'Rc17000000000'; $add = { param($sp) [IO.File]::WriteAllText((Join-Path $sp 'deploy\new.csv'), 'new') }
$r = Run @{ Source = $s17; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; BeforeRemove = $add }
Check 'a file that appears after the check stays' ($r.code -eq 3 -and $r.out -match 'appeared in the source' -and (Test-Path (Join-Path $s17 'deploy\new.csv')) -and @(Get-ChildItem $s17 -Recurse -File).Count -eq 1) $r.out
# 18. A file added before the check (after the manifest) is also caught by it: nothing removed.
$s18 = Fixture 'Rc18000000000'; $add2 = { param($zp) [IO.File]::WriteAllText((Join-Path $s18 'extra.csv'), 'extra') }
$r = Run @{ Source = $s18; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; AfterZip = $add2 }
Check 'a file added after the manifest: nothing removed' ($r.code -eq 3 -and $r.out -match 'new extra.csv' -and @(Get-ChildItem $s18 -Recurse -File).Count -eq 4) $r.out
# 19. Codex P1 4562087122: while a file is held for its check, a rename-and-replace at its path must be refused (no sharing),
#     and the delete goes through the handle; every archived file is removed and nothing unarchived is created or deleted.
$s19 = Fixture 'Rc19000000000'; $global:swap19 = $null
$swap = { param($p) if (-not $global:swap19) { try { [IO.File]::Move($p, "$p.moved"); [IO.File]::WriteAllText($p, 'replacement'); $global:swap19 = 'done' } catch { $global:swap19 = 'refused' } } }
$r = Run @{ Source = $s19; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; DuringRemove = $swap }
Check 'a rename-and-replace during the removal is refused; every archived file goes, nothing else' ($r.code -eq 0 -and $global:swap19 -eq 'refused' -and -not (Test-Path $s19) -and (Test-Path (Join-Path $dest 'Rc19000000000.zip'))) "code=$($r.code) swap=$($global:swap19) $($r.out)"
# 20. Codex P2 4562087134: the zip's creation fails after the manifest was written (a source file locked): the run removes
#     its own manifest and partial zip, the source stays, and a retry is not refused (create-only).
$s20 = Fixture 'Rc20000000000'; $global:lock20 = $null
$lock = { param($sp) $global:lock20 = [IO.File]::Open((Join-Path $sp 'equity.csv'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None) }
$r = Run @{ Source = $s20; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; BeforeZip = $lock }
if ($global:lock20) { $global:lock20.Dispose() }
Check 'a failed zip leaves no zip or manifest; the source stays' ($r.code -eq 3 -and $r.out -match 'ZIP FAILED' -and -not (Test-Path (Join-Path $dest 'Rc20000000000.zip')) -and -not (Test-Path (Join-Path $dest 'Rc20000000000.zip.manifest.csv')) -and @(Get-ChildItem $s20 -Recurse -File).Count -eq 3) $r.out
$r = Run @{ Source = $s20; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty }
Check 'the retry after a failed zip archives normally' ($r.code -eq 0 -and -not (Test-Path $s20)) $r.out
# 21-22 (Claude-Mac 6850291527): a read-only source file is archived and removed through its handle like any other; and an
#     unexpected failure during the removal writes the partial row and exits 3, never a bare throw.
$s21 = Fixture 'Rc21000000000'; foreach ($ro in (Join-Path $s21 'equity.csv'), (Join-Path $s21 'deploy\blob.bin')) { Set-ItemProperty -LiteralPath $ro -Name IsReadOnly -Value $true }
$r = Run @{ Source = $s21; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty }
Check 'read-only source files are removed through the handle' ($r.code -eq 0 -and -not (Test-Path $s21)) $r.out
$s22 = Fixture 'Rc22000000000'; $global:n22 = 0
$boom = { param($p) $global:n22++; if ($global:n22 -eq 2) { throw 'simulated failure while removing' } }
$r = Run @{ Source = $s22; DestRoot = $dest; RemoveSource = $true; NeedsLive = $nlEmpty; DuringRemove = $boom }
$p22 = @(Import-Csv (Join-Path $dest 'ARCHIVE-INDEX.csv') | Where-Object { $_.source -eq $s22 })
Check 'a failure during the removal writes the partial row and exits 3' ($r.code -eq 3 -and $r.out -match 'REMOVAL FAILED' -and $p22.Count -eq 1 -and $p22[0].status -eq 'partial' -and [int]$p22[0].files_removed -eq 1 -and @(Get-ChildItem $s22 -Recurse -File).Count -eq 2) "$($r.out) | $($p22 | ConvertTo-Json -Compress)"
$c1 = @(Import-Csv (Join-Path $dest 'ARCHIVE-INDEX.csv') | Where-Object { $_.source -eq $s1 })
Check 'a full removal has a complete index row' ($c1.Count -eq 1 -and $c1[0].status -eq 'complete' -and [int]$c1[0].files_removed -eq 3) ($c1 | ConvertTo-Json -Compress)
Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
"RESULT: $(if ($fail) { "$fail FAILED" } else { 'all passed' })"
exit $fail
