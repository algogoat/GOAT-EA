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

    def test_vps_setup_is_registered_in_names_and_the_customer_skills_table(self):
        root=Path(__file__).parent
        self.assertIn('goat-vps-setup',NAMES)
        table=(root/'CUSTOMER-SKILLS.md').read_text(encoding='utf-8')
        linked=re.findall(r'\| \[([a-z0-9-]+)\]\(skills/([a-z0-9-]+)/SKILL\.md\) \|',table)
        self.assertEqual(sorted(name for name,_ in linked),sorted(NAMES))
        self.assertTrue(all(name==folder for name,folder in linked))
        self.assertIn('goat-vps-setup',[row['name'] for row in customer_skills()])

    def test_vps_setup_keeps_disclosure_user_only_payment_and_no_real_links(self):
        root=Path(__file__).parent
        body=' '.join((root/'skills/goat-vps-setup/SKILL.md').read_text(encoding='utf-8').split())
        # The disclosure is said word for word before every partner link.
        self.assertIn('GOAT may earn a commission if you sign up through this link; your price is the same '
                      'or lower. Our ranking comes from our own benchmark, not commission.',body)
        # Links come only from the partner configuration placeholder; none are shipped yet.
        self.assertIn('<GOAT_VPS_REFERRAL_LINKS>',body)
        self.assertIsNone(re.search(r'https?://',body))
        for phrase in ('never type or ask for a password','Signup, payment, every password',
                       'signs up and pays on the provider',"Never invent a provider ranking",
                       'Trade','Lab','Pro Lab','2 vCPU, 4 GB RAM, 80 GB','4-6 **dedicated** vCPU, 16 GB RAM, 200 GB NVMe',
                       '8-16 **dedicated** vCPU, 32 GB RAM, 400 GB+ NVMe','resource-profile','benchmark-report',
                       'powercfg','Remote Control','**disconnects**','30 GB','Demo accounts only',
                       'GOAT > Live','cockpit.connectAccount','Research sharing','private by default'):
            self.assertIn(phrase,body)

    def test_going_live_guides_point_to_the_live_connect_step(self):
        root=Path(__file__).parent
        for guide in ('AGENT-START-HERE.md','GOAT-OPERATING-MODEL.md','skills/goat-portfolio-build/SKILL.md'):
            text=' '.join((root/guide).read_text(encoding='utf-8').split())
            self.assertIn('GOAT > Live',text,guide)
            self.assertIn('Settings > Account > Research sharing',text,guide)
        start=' '.join((root/'AGENT-START-HERE.md').read_text(encoding='utf-8').split())
        for phrase in ('cockpit.discoverAccounts','cockpit.connectAccount','live.connected','cockpit.linkPortfolio',
                       'goat-vps-setup'):
            self.assertIn(phrase,start)


if __name__=='__main__':unittest.main()
