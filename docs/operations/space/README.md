# Space on the Ops PC

Ops owns disk space on this PC as a standing job (Vince, relayed by Claude-Mac on goatai#2750 6845863463: "use G: for
archives!! Ops needs to smartly manage space there anyways"). C: and G: are one 2 TB NVMe; E: and F: are Vince's own
drives and are never written; D: holds Vince's own files beside two of our old archives.

Measured on 2026-11-13 (goatai#2750 6846190790): about 80 GB a week of research output lands on C: (36 GB of new run
folders under `Common\Files\GOAT`, 44 GB of product evidence in the suite). A judged run folder is 99% CSV and zips to
about 10% of its size (1,464 MB to 151 MB).

## zip-archive.ps1

Archives one folder as a zip by the per-file method: every source file is hashed into a manifest; the zip is written to
the destination with the manifest beside it; every entry is read back and hashed; any extra, missing or different entry
deletes the zip, leaves the source untouched and exits 3. Only with `-RemoveSource`, and only after every file matched, is
the source removed and a row appended to `ARCHIVE-INDEX.csv` in the destination. A source written after the zip is never
deleted: before any removal every source file is hashed again (a changed, missing or new file deletes the zip, removes
nothing, exit 3), and each file is then opened with no sharing at all (nobody can read, write, rename or replace it
meanwhile), hashed through that handle and deleted through that same handle, never by path, only if it still matches (a
file that changed stays, the zip is kept, the index gets a `partial` row, exit 3); a file that appears later stays with its
folder. A manifest or zip that fails while being written (disk full, an unreadable file) is removed by the run, so a retry
is not refused. It refuses (exit 2) a source file with a named NTFS stream (the zip would not hold it and the removal
would destroy it), a source or destination on E: or F:, a source or destination root that is
(or sits under) a junction or symlink (a removal must never reach real files on another volume through a link),
`-RemoveSource` without `-NeedsLive`, a source on the needs-live list (or inside or above a listed path), a junction or
symlink inside the source, an existing zip, and an empty source.

For a finished catch-up's evidence in the suite, or a native run folder, use the product's own `evidence-archive` verb
instead (`--run-folders` for run folders; a keep-list of what preregs and the book cite): it moves to another volume with a
pointer every reader follows. This tool is for Ops' own folders the product does not own.

```
powershell -NoProfile -File docs\operations\space\zip-archive.ps1 -Source <folder> -DestRoot G:\<archive root> -NeedsLive <list> [-DryRun] [-RemoveSource]
powershell -NoProfile -File docs\operations\space\zip-archive.test.ps1
```

The 37 tests cover the round trip, a corrupted member, a short write, a missing entry, E:/F:, the needs-live list,
create-only, a junction inside the source, an empty source, a dry run, `-RemoveSource` without `-NeedsLive`, a junction as
the source root, as the destination root and above the source, a source changed after the zip, changed during the removal
(with its `partial` index row), grown by a file after the check and grown by a file after the manifest, a rename-and-replace
attempted while a file is held, a zip that fails after its manifest (and the retry), the `complete` index row, read-only source files (deleted through the handle with `FileDispositionInfoEx` ignoring the read-only attribute) an unexpected failure during the removal (a `partial` row and exit 3, never a bare throw), a run that loses a race for the same zip name (it refuses; the winner's zip and manifest stay), a zip of the same name that is not this run's (its cleanup never removes it) a hidden subfolder (removed, the run completes), a source file with a named NTFS stream (refused before any write) and a stream added after the check (the removal stops at that file, which keeps it), a source over 2 GiB and a single file over 4 GiB (zip64; both stay in the suite for good), the long-path forms (\\?\ for a local path, \\?\UNC\ for a UNC one) and a source with empty folders (their backslash-named directory entries are not mistaken for extra files). Each rule
removed in turn fails exactly its own cases (the verification: the three corruption cases; the link chain: the three
junction cases; the needs-live requirement, the re-hash, the hash at removal, the appeared-file check, no sharing, delete by
handle, the failed-zip cleanup and the partial row: theirs).
