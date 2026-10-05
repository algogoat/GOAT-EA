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
        self.assertIn('GOAT may earn a commission if you sign up through this link. '
                      'Our ranking comes from our own benchmark, not commission.',body)
        # No price promise until a signed partner agreement says so.
        for claim in ('same or lower','price is the same','lower price','far faster per dollar'):
            self.assertNotIn(claim,body)
        # Links come only from the partner configuration placeholder; none are shipped yet.
        self.assertIn('<GOAT_VPS_REFERRAL_LINKS>',body)
        self.assertIsNone(re.search(r'https?://',body))
        for phrase in ('never type or ask for a password','Signup, payment, every password',
                       'signs up and pays on the provider',"Never invent a provider ranking",
                       'Trade','Lab','Pro Lab','2 vCPU, 4 GB RAM, 80 GB','4-6 **dedicated** vCPU, 16 GB RAM, 200 GB NVMe',
                       '8-16 **dedicated** vCPU, 32 GB RAM, 400 GB+ NVMe','resource-profile','benchmark-report',
                       'powercfg','Remote Control','**disconnects**','30 GB','Demo accounts only',
                       'long, strong and used nowhere else','Establish it before they buy',
                       'at most 18 hours','**Download only**'):
            self.assertIn(phrase,body)

    def test_vps_setup_size_check_has_tolerance_and_never_accuses(self):
        body=' '.join((Path(__file__).parent/'skills/goat-vps-setup/SKILL.md').read_text(encoding='utf-8').split())
        for phrase in ('with tolerance','15.9 GB','within 10 %','logical cores are at least',
                       'please check it with the provider','Never say they received less than they paid for'):
            self.assertIn(phrase,body)
        self.assertNotIn('smaller plan than they paid for',body)

    def test_live_connect_is_demo_only_and_same_machine(self):
        # Mirrors goatai liveCockpitService: linkPortfolio refuses any account not verified demo, and an account
        # connected from another machine (source ea-reporting) can never be verified, so it stays display-only.
        root=Path(__file__).parent
        skill=' '.join((root/'skills/goat-vps-setup/SKILL.md').read_text(encoding='utf-8').split())
        start=' '.join((root/'AGENT-START-HERE.md').read_text(encoding='utf-8').split())
        for text,name in ((skill,'skill'),(start,'start page')):
            for phrase in ('emo accounts only','same machine as that MT5','cockpit.discoverAccounts',
                           'cockpit.connectAccount @{candidateId=...}','live.connected','**Check account type**',
                           "ui.highlight' @{target='live.account.checkType'}",'cockpit.linkPortfolio @{accountKey=...}',
                           'cockpit.linkPortfolio` refuses it','display-only','Research sharing'):
                self.assertIn(phrase,text,name)
            # The cross-machine route is never offered as a way to connect.
            self.assertNotIn('ea-reporting',text,name)
            self.assertNotIn('host:"vps"',text,name)
        self.assertIn('Not supported: connecting an account from a **different** computer',skill)
        self.assertIn('**private by default**',skill)
        for guide in ('GOAT-OPERATING-MODEL.md','skills/goat-portfolio-build/SKILL.md'):
            text=' '.join((root/guide).read_text(encoding='utf-8').split())
            for phrase in ('GOAT > Live','emo accounts only','same machine as that MT5','display-only',
                           'Settings > Account > Research sharing'):
                self.assertIn(phrase,text,guide)
        self.assertIn('goat-vps-setup',start)

if __name__=='__main__':unittest.main()
