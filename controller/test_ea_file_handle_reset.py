"""GOAT-EA#361: a global file handle must never keep its number after it is closed.

MT5 reuses a freed handle number for the next FileOpen. OnTesterInit opened and closed FileTester_handle without resetting it
(under Opti_PF_MRFp / Opti_PF_MRF_SRp, the default Mode_Opti), the seed-farming XML then took that number, and OnTesterDeinit's
"close if not INVALID_HANDLE" closed the XML before SeedFarmingFinalize wrote </Table></Worksheet></Workbook>: a seed that ended
below its frame target was renamed truncated (hunt-banker-ws2b-seed-1126, 2026-11-27, "Incomplete or invalid seed XML").

Static check of the EA source (GOAT V1.49.mq5 and the .mqh files beside it): every FileClose of a GLOBAL handle variable either
goes through GoatFileCloseReset or resets that variable to INVALID_HANDLE in the same statement block, and GoatFileCloseReset
itself closes only a valid handle and always resets it. Locals (declared inside a function) are out of scope.
    python -m unittest test_ea_file_handle_reset      (from controller/)
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MQ5 = ROOT / 'GOAT V1.49.mq5'
CLOSE = re.compile(r'(?<![\w:])FileClose\(\s*([A-Za-z_]\w*)\s*\)')


def read(path):
    raw = path.read_bytes()
    if raw[:2] == b'\xff\xfe':
        return raw[2:].decode('utf-16-le')
    return raw.decode('utf-8-sig')


def strip_comment(line):
    i = line.find('//')
    return line if i < 0 else line[:i]


def global_int_names(texts):
    """Names declared as int at column 0 (file scope), e.g. `int FileCSV_handle=INVALID_HANDLE,FileSET_handle=...;`."""
    names = set()
    for text in texts:
        for line in text.splitlines():
            code = strip_comment(line)
            m = re.match(r'^(?:static\s+)?int\s+(.+);', code)
            if not m or '(' in m.group(1).split('=')[0]:
                continue
            for part in m.group(1).split(','):
                name = part.split('=')[0].strip()
                if re.fullmatch(r'[A-Za-z_]\w*', name):
                    names.add(name)
    return names


def unsafe_closes(text, globals_):
    """(line number, handle, line) for each FileClose of a global handle that is neither the helper's own close nor followed by
    `<handle>=INVALID_HANDLE` later on the same line or on the next code line (SeedFarmingFinalize resets on the next line)."""
    bad = []
    lines = text.splitlines()
    in_helper = False
    for n, line in enumerate(lines, 1):
        code = strip_comment(line)
        if re.match(r'^void\s+GoatFileCloseReset\s*\(', code):
            in_helper = True
        elif in_helper and re.match(r'^\s*}\s*$', code):
            in_helper = False
        if in_helper:
            continue
        for m in CLOSE.finditer(code):
            name = m.group(1)
            if name not in globals_:
                continue
            rest = code[m.end():]
            nxt = next((strip_comment(x) for x in lines[n:n + 3] if strip_comment(x).strip()), '')
            reset = re.compile(r'\b' + re.escape(name) + r'\s*=\s*INVALID_HANDLE')
            if reset.search(rest) or reset.match(nxt.strip()):
                continue
            bad.append((n, name, line.strip()))
    return bad


class EaFileHandleResetTest(unittest.TestCase):
    def setUp(self):
        self.files = [MQ5] + sorted(ROOT.glob('*.mqh'))
        self.texts = {p.name: read(p) for p in self.files}
        self.globals = global_int_names(self.texts.values())

    def test_the_globals_of_the_incident_are_found(self):
        for name in ('FileTester_handle', 'FileCSV_handle', 'FileSET_handle'):
            self.assertIn(name, self.globals)

    def test_no_global_handle_keeps_its_number_after_close(self):
        bad = []
        for name, text in self.texts.items():
            bad += ['%s:%d %s: %s' % (name, n, h, line) for n, h, line in unsafe_closes(text, self.globals)]
        self.assertEqual(bad, [], 'a global file handle is closed without being reset (GOAT-EA#361):\n' + '\n'.join(bad))

    def test_helper_closes_only_a_valid_handle_and_always_resets(self):
        text = self.texts[MQ5.name]
        m = re.search(r'void\s+GoatFileCloseReset\s*\(\s*int\s*&\s*(\w+)\s*\)\s*\{(.*?)\n\s*\}', text, re.S)
        self.assertIsNotNone(m, 'GoatFileCloseReset(int &handle) is missing')
        p, body = m.group(1), m.group(2)
        self.assertRegex(body, r'if\s*\(\s*%s\s*!=\s*INVALID_HANDLE\s*\)\s*FileClose\(\s*%s\s*\)' % (p, p))
        self.assertRegex(body, r'\n\s*%s\s*=\s*INVALID_HANDLE\s*;' % p, 'the reset must be unconditional')

    def test_tester_init_forgets_the_fitness_handle(self):
        text = self.texts[MQ5.name]
        m = re.search(r'\nint\s+OnTesterInit\s*\(\s*\)(.*?)\n}', text, re.S)
        self.assertIsNotNone(m, 'OnTesterInit not found')
        body = m.group(1)
        if 'FileTester_handle' in body:
            self.assertIn('GoatFileCloseReset(FileTester_handle)', body)

    def test_the_incident_shape_is_caught(self):
        # Positive control: the pre-fix OnTesterInit and OnTesterDeinit lines are refused by the same check.
        incident = ('    FileTester_handle = FileOpen(f,FILE_TXT|FILE_WRITE|FILE_COMMON);\n'
                    '    FileWrite(FileTester_handle,0.02);\n'
                    '    FileClose(FileTester_handle);\n'
                    '   if(FileCSV_handle    != INVALID_HANDLE) {FileClose(FileCSV_handle);     Sleep(100);}\n')
        found = unsafe_closes(incident, {'FileTester_handle', 'FileCSV_handle'})
        self.assertEqual([h for _, h, _ in found], ['FileTester_handle', 'FileCSV_handle'])
        fixed = '   if(FileCSV_handle != INVALID_HANDLE) {GoatEquityCsvFinalRow(); FileClose(FileCSV_handle); FileCSV_handle=INVALID_HANDLE;}\n'
        self.assertEqual(unsafe_closes(fixed, {'FileCSV_handle'}), [])


if __name__ == '__main__':
    unittest.main()
