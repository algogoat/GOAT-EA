# Ops 2026-11-13: the disk start floor for every machine queue (dot-source it; no copies of the logic).
#
# Why (goatai#2750 6845735751, Claude-Mac 6845747846): on 2026-11-13 at 06:03Z C: had 6.78 GB free and fell about 49 MB a
# minute while two queues wrote run folders and catch-up evidence; the product's own 5 GiB guard was about 35 minutes away and
# a full disk about 2 hours. It was found by chance. C: holds the suite state, the terminals' data and the tester agents.
# Rule: a seed, Prove batch or catch-up is not STARTED while C: has less than 15 GB free. A read that fails refuses too.
$script:DiskFloorGB = 15
$script:DiskFreeBytes = { param([string]$Drive) (Get-Volume -DriveLetter $Drive -ErrorAction Stop).SizeRemaining }

function Get-DiskFloorReason([double]$MinFreeGB = $script:DiskFloorGB, [string]$Drive = 'C') {
  # $null = enough room. Any string = do not start.
  try { $b = [double](& $script:DiskFreeBytes $Drive) } catch { return ('{0}: free space could not be read' -f $Drive) }
  if ($b -lt $MinFreeGB * 1GB) { return ('{0}: has {1:N1} GB free, under the {2:N0} GB start floor' -f $Drive, ($b / 1GB), $MinFreeGB) }
  return $null
}
