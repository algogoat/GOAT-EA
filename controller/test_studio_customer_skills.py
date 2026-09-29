"""The shipped skill inventory must be usable without developer machine state."""
from pathlib import Path
import re
import unittest
from studio_customer_skills import customer_skills,NAMES


class CustomerSkillsTests(unittest.TestCase):
    def test_inventory_is_complete_hash_bound_and_portable(self):
        rows=customer_skills()
        self.assertEqual([row['name'] for row in rows],list(NAMES))
        for row in rows:
            body=Path(row['path']).read_text(encoding='utf-8-sig')
            self.assertRegex(row['sha256'],r'^[0-9a-f]{64}$')
            self.assertTrue(row['description'])
            for private in ('C:/Users/web','C:\\Users\\web','G:/GOAT','G:\\GOAT','.codex/',
                            '3000082754','209.145.63.19','studio_restart_runner'):
                self.assertNotIn(private,body,row['name'])
            for target in re.findall(r'\]\(([^)]+)\)',body):
                if '://' not in target:
                    self.assertTrue((Path(row['path']).parent/target).resolve().is_file(),target)

    def test_skill_routes_preserve_real_capability_limits(self):
        root=Path(__file__).parent/'skills'
        seed=(root/'goat-seed-research/SKILL.md').read_text()
        repair=(root/'goat-repair-report/SKILL.md').read_text()
        optimize=(root/'goat-optimize/SKILL.md').read_text()
        self.assertIn('native qualification',seed)
        self.assertIn('support.prepareReport',repair)
        self.assertIn('exact preview',repair)
        self.assertIn('1-minute OHLC',optimize)
        self.assertIn('explicit choice',optimize)


if __name__=='__main__':unittest.main()
