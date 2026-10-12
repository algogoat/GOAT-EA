"""EA-MAILBOX-SHARE-01 (B44 item 11): the lint passes on the tree and catches each violation on fixtures.

Run: python scripts/test_lint_ea_mailbox_share.py (the lint module sits next to this file).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_ea_mailbox_share as lint   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
READER = '''bool GoatSetupRead(const string path,string &body)
{
   int h=FileOpen(path,%s);
   return h!=INVALID_HANDLE;
}
void GoatSetupPoll()
{
   string root="GOAT\\\\AgentSetup\\\\"+GoatTerminalToken()+"\\\\";
   int lock=FileOpen(root+"owner.lock",FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON);
   string request="";
   if(!GoatSetupRead(root+"request.json",request)) return;
}
'''


def report(main='', **headers):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / lint.MAIN).write_text(main, encoding='utf-8')
        for name, text in headers.items():
            (root / (name + '.mqh')).write_text(text, encoding='utf-8')
        return lint.Linter(lint.load(root)).run()


class TreeTests(unittest.TestCase):
    def test_the_tree_passes(self):
        result = lint.Linter(lint.load(ROOT)).run()
        self.assertEqual(result['findings'], [], result['findings'])
        where = {item['where'].split(':')[0] for item in result['checked']}
        self.assertIn('GOATSetupControl.mqh', where)
        self.assertIn('GOATPortfolioSetupControl.mqh', where)
        setup = [item for item in result['checked'] if item['where'].startswith('GOATSetupControl.mqh') and item['verdict'] == 'shared read']
        self.assertEqual(len(setup), 1, 'GoatSetupRead is a checked shared read')
        self.assertIn('request.json', setup[0]['mailbox'])
        locks = [item for item in result['checked'] if item['verdict'] == 'lock allowlist']
        self.assertTrue(any('owner.lock' in item['path'] for item in locks))

    def test_main_exit_code(self):
        self.assertEqual(lint.main(['--root', str(ROOT)]), 0)


class FixtureTests(unittest.TestCase):
    def test_the_10_12_read_fails(self):
        result = report(Setup=READER % 'FILE_READ|FILE_BIN|FILE_COMMON')
        self.assertFalse(result['ok'])
        self.assertEqual([f['verdict'] for f in result['findings']], ['reader-only open without FILE_SHARE_READ'])
        self.assertEqual(result['findings'][0]['where'], 'Setup.mqh:3')
        self.assertIn('request.json', result['findings'][0]['mailbox'], 'followed from the call site')

    def test_shared_read_passes_and_share_write_fails(self):
        self.assertTrue(report(Setup=READER % 'FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ')['ok'])
        result = report(Setup=READER % 'FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE')
        self.assertEqual([f['verdict'] for f in result['findings']], ['reader-only open with FILE_SHARE_WRITE (torn read)'])

    def test_direct_paths_locals_and_every_mailbox_name(self):
        for path in ('"GOAT\\\\AgentPortfolio\\\\x\\\\registration.json"', 'root+id+".json"', 'name+".request.json"',
                     'base+".pending"', '"GOATStudio\\\\native-gate\\\\request.json"'):
            text = ('void F(const string id,const string name,const string base)\n{\n   string root="GOAT\\\\AgentPortfolio\\\\";\n'
                    '   int h=FileOpen(%s,FILE_READ|FILE_BIN|FILE_COMMON);\n}\n' % path)
            with self.subTest(path=path):
                self.assertFalse(report(Portfolio=text)['ok'])
        local = 'void F()\n{\n   string p="GOAT\\\\AgentSetup\\\\t\\\\request.json";\n   int h=FileOpen(p,FILE_READ|FILE_BIN);\n}\n'
        self.assertFalse(report(Setup=local)['ok'], 'a local is followed to its value')

    def test_lock_allowlist_and_read_write_outside_it(self):
        self.assertTrue(report(Setup=READER % 'FILE_READ|FILE_BIN|FILE_SHARE_READ')['ok'], 'owner.lock is allowlisted')
        rw = 'void F()\n{\n   string root="GOAT\\\\AgentSetup\\\\";\n   int h=FileOpen(root+"request.json",FILE_READ|FILE_WRITE|FILE_BIN);\n}\n'
        self.assertEqual([f['verdict'] for f in report(Setup=rw)['findings']],
                         ['read-write open of a mailbox file outside the lock allowlist'])

    def test_unrelated_files_writers_and_comments_are_not_findings(self):
        text = ('void F()\n{\n   int a=FileOpen("GOAT\\\\Diagnostics\\\\x.log",FILE_READ|FILE_TXT);\n'
                '   string t="GOAT\\\\AgentSetup\\\\r.json.1.pending";\n   int b=FileOpen(t,FILE_WRITE|FILE_TXT);\n'
                '   // int c=FileOpen("GOAT\\\\AgentSetup\\\\request.json",FILE_READ);\n'
                '   /* int d=FileOpen("GOAT\\\\AgentSetup\\\\request.json",FILE_READ); */\n}\n')
        result = report(Setup=text)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['writers']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=1)
