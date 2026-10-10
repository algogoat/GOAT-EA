"""Named pending-job reservation: a dead pending job never blocks later batches."""
import unittest

from campaign_ledger import sha
from studio_queue import reserve_job


def job(job_id, status='pending'):
    config = dict(batch_members=[{'symbol': job_id}])
    return dict(job_id=job_id, status=status, configuration=config, configuration_sha256=sha(config))


class NamedReservationTests(unittest.TestCase):
    def state(self, *jobs):
        return dict(queue=list(jobs), generation=2, owner='agent', revision=7)

    def payload(self, item):
        return dict(job_id=item['job_id'], configuration_sha256=item['configuration_sha256'], package_sha256='b'*64)

    def test_a_later_pending_job_can_be_reserved_past_a_dead_one(self):
        dead, wanted = job('dead'), job('wanted')
        jobs = reserve_job(self.state(dead, wanted), self.payload(wanted), 'r1')
        self.assertEqual([j['status'] for j in jobs], ['pending', 'reserved'])
        self.assertIs(jobs[1]['reservation']['launch_permitted'], False)

    def test_non_pending_or_mismatched_jobs_still_refuse(self):
        started, wanted = job('started', 'starting'), job('wanted')
        with self.assertRaisesRegex(ValueError, 'Only a pending job'):
            reserve_job(self.state(started, wanted), self.payload(started), 'r1')
        with self.assertRaisesRegex(ValueError, 'Only a pending job'):
            reserve_job(self.state(wanted), dict(self.payload(wanted), job_id='missing'), 'r1')
        with self.assertRaisesRegex(ValueError, 'configuration mismatch'):
            reserve_job(self.state(wanted), dict(self.payload(wanted), configuration_sha256='c'*64), 'r1')


if __name__ == '__main__':
    unittest.main()
