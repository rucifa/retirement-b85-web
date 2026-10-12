"""Contract-level calendar first-year tests against real, unchanged B+85 policy."""
import copy
import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bridge
import workflow
from calendar_first_year import MODE, fraction_for

BASE={'decision_date':'2036-10-12','start_age':'54','investment_twd':'27000000',
      'cash_twd':'2400000','stock_bond':'70/30','cpi_2026':'110',
      'decision_cpi':'125','decision_cpi_release':'2036-10-07','planned_extra_twd':'30000'}

class CalendarFirstYear(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        bridge.STATE_PATH=Path(self.temp.name)/'records.json'
        workflow.INNER_DRAWS=256
        bridge.initialize(None)
    def tearDown(self): self.temp.cleanup()
    def call(self,kind,data=None):
        return json.loads(bridge.dispatch(json.dumps({'op':kind,'data':data or {}},ensure_ascii=False)))
    def start(self,**kw): return self.call('approve',dict(BASE,**kw))
    def test_inclusive_calendar_fraction_and_leap(self):
        self.assertEqual(fraction_for('2026-01-01')[:2],(365,365))
        self.assertEqual(fraction_for('2026-10-12')[:2],(81,365))
        self.assertEqual(fraction_for('2036-10-12')[:2],(81,366))
        self.assertEqual(fraction_for('2036-12-31')[:2],(1,366))
        self.assertEqual(fraction_for('2036-02-29')[:2],(307,366))
    def test_actual_policy_budget_is_partial_and_conserved(self):
        raw=self.start()
        pub=raw['data']['approval']
        record=raw['record']['years'][0]
        app=record['approval'];p=app['policy_preview'];o=app['opening']
        self.assertEqual(app['mode'],MODE)
        self.assertEqual((pub['calendar_days'],pub['calendar_year_days']),(81,366))
        self.assertEqual(pub['period_end'],'2036-12-31')
        self.assertAlmostEqual(pub['living_authorized_twd'],
          pub['full_year_living_reference_twd']*81/366,delta=0.05)
        self.assertAlmostEqual(app['spending_reserved_m'],p['living_pool_paid_m']+p['car_paid_m']+p['extra_mandatory_paid_m'])
        self.assertAlmostEqual(o['investment_m']+o['safety_cash_m'],
           app['spending_reserved_m']+p['investment_before_return_m']+p['safety_cash_before_return_m'])
        self.assertFalse(raw['data']['overview']['policy_active'])
        self.assertIn('全年政策',pub['pos_period_label'])
    def test_policy_engine_exact_parity_and_released_funds(self):
        from policy.simple_annual_ledger import approve_year
        from workflow import hydrate_approval, policy_config
        record=self.start()['record']
        plan=record['plan']
        adapted=hydrate_approval(record['years'][0]['approval'])
        full=approve_year(adapted.opening,policy_config(plan),
                          n_inner=workflow.INNER_DRAWS,seed=workflow.SEED)
        before=full.policy_preview
        after=adapted.policy_preview
        days,total,share=fraction_for(adapted.opening.decision_date)
        self.assertEqual((days,total),(81,366))
        self.assertEqual(after.pos,before.pos)
        self.assertEqual(after.normal_pos,before.normal_pos)
        self.assertEqual(after.sticky_after,before.sticky_after)
        self.assertEqual(after.b85_restored,before.b85_restored)
        self.assertEqual(after.car_paid_m,before.car_paid_m)
        self.assertEqual(after.extra_mandatory_paid_m,before.extra_mandatory_paid_m)
        self.assertAlmostEqual(after.living_pool_paid_m,before.living_pool_paid_m*share)
        self.assertAlmostEqual(after.bridge_from_cash_m,before.bridge_from_cash_m*share)
        self.assertAlmostEqual(after.investment_before_return_m-before.investment_before_return_m,
                               (before.living_pool_paid_m-before.bridge_from_cash_m)*(1-share))
        self.assertAlmostEqual(after.safety_cash_before_return_m-before.safety_cash_before_return_m,
                               before.bridge_from_cash_m*(1-share))
        self.assertTrue(record['years'][0]['calendar_first_year']['pos_full_year_reference_only'])

    def test_january_first_is_exact_full_year(self):
        first=self.start(decision_date='2036-01-01',
                         decision_cpi_release='2035-12-20')
        self.assertEqual(first['data']['approval']['calendar_days'],366)
        self.assertEqual(first['data']['approval']['calendar_fraction'],1)
        self.assertAlmostEqual(first['data']['approval']['living_authorized_twd'],
                               first['data']['approval']['full_year_living_reference_twd'],delta=.01)

    def test_december31_one_day_can_close_same_day(self):
        o=self.start(decision_date='2036-12-31',decision_cpi_release='2036-12-20')
        self.assertEqual(o['data']['approval']['calendar_days'],1)
        c=self.call('demo-close')['data']
        self.assertEqual(c['closing_date'],'2036-12-31')
        result=self.call('close',c)['data']['year_close']
        self.assertEqual(result['status'],'CLOSED')
        self.assertAlmostEqual(result['closing']['balance_reconciliation_error_twd'],0,delta=.02)
    def test_closing_and_next_january_full_year(self):
        first=self.start()
        close=self.call('demo-close')['data']
        closed=self.call('close',close)
        self.assertEqual(closed['data']['year_close']['status'],'CLOSED')
        self.assertAlmostEqual(closed['data']['year_close']['closing']['net_real_portfolio_return_pct'],5,delta=.01)
        second=self.call('approve',{'decision_date':'2037-01-15','decision_cpi':'126',
                   'decision_cpi_release':'2037-01-10','planned_extra_twd':'0'})
        item=second['data']['approval']
        self.assertFalse(item['calendar_first_year'])
        self.assertEqual(item['calendar_fraction'],1)
        self.assertEqual(item['age'],55)
        self.assertEqual(second['record']['years'][1]['approval']['mode'],'SYNTHETIC_RESEARCH_ONLY')
        # Canonical year-end is still Dec31 after next complete annual decision.
        self.assertEqual(item['period_end'],'2037-12-31')
    def test_followup_non_january_rejected(self):
        self.start()
        self.call('close',self.call('demo-close')['data'])
        with self.assertRaisesRegex(workflow.InputError,'一月'):
            self.call('approve',{'decision_date':'2037-03-01','decision_cpi':'125',
                          'decision_cpi_release':'2037-02-15','planned_extra_twd':'0'})
    def test_import_rejects_tampered_calendar_days_even_with_new_digest(self):
        self.start()
        exp=self.call('export')['data']
        exp['payload']['years'][0]['calendar_first_year']['calendar_days']=82
        exp['sha256']=workflow.digest(exp['payload'])
        with self.assertRaisesRegex(workflow.InputError,'曆年制'):
            self.call('import',exp)
    def test_import_preserves_verified_legacy_full_year(self):
        # New contract metadata is supported; legacy backups lacking it remain
        # accepted under the earlier rules without silently applying proration.
        raw=self.start()
        exp=self.call('export')['data']
        bridge.initialize(None)
        restored=self.call('import',exp)
        self.assertEqual(restored['data']['years'][0]['calendar_days'],81)

if __name__=='__main__':unittest.main()
