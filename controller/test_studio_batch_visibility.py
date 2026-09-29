import copy
import unittest
from studio_bridge import display_state


class BatchVisibilityTests(unittest.TestCase):
    def state(self):
        members=[dict(tester=dict(Symbol='EURUSD',Period='M1',Model=1),
                      strategy=dict(values={'EA_Desc':'Example '+str(i)})) for i in range(115)]
        job=dict(job_id='batch',status='running',configuration_sha256='retained',source_revision=1,
                 configuration=dict(tester=members[0]['tester'],batch_members=members),
                 native_observation={'native':dict(observed_at='2026-09-29T00:00:00Z',members=[
                     dict(index=i,status=status) for i,status in enumerate(
                         ['native_completed','native_error','native_cancelled','native_ongoing']+
                         ['native_pending']*111)])})
        return dict(tester_draft={},export_draft={},queue=[job])

    def test_all_members_and_disjoint_outcome_counts(self):
        state=self.state();before=copy.deepcopy(state)
        view=display_state(state)['batch_view']
        self.assertEqual((view['total'],view['completed'],view['failed'],view['cancelled'],
                          view['remaining'],view['active'],view['pending']), (115,1,1,1,112,1,111))
        self.assertEqual(len(view['members']),115)
        self.assertEqual(view['members'][3]['status'],'ongoing')
        self.assertEqual(view['members'][114]['strategy'],'Example 114')
        self.assertEqual(state,before)

    def test_missing_observation_does_not_claim_completion(self):
        state=self.state();state['queue'][0].pop('native_observation')
        state['queue'][0]['status']='completed'
        view=display_state(state)['batch_view']
        self.assertEqual((view['completed'],view['unobserved'],view['remaining']),(0,115,115))

    def test_pending_members_and_active_batch_selected_over_old_history(self):
        state=self.state();old=copy.deepcopy(state['queue'][0]);old['job_id']='old';old['status']='cancelled'
        state['queue'].insert(0,old)
        self.assertEqual(display_state(state)['batch_view']['job_id'],'batch')
        state['queue'][1]['status']='pending';state['queue'][1].pop('native_observation')
        self.assertEqual(display_state(state)['batch_view']['pending'],115)


if __name__=='__main__': unittest.main()
