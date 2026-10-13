import copy,json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
import bridge,workflow,large_expenses as large
from projection_research import trace_paths,project_saved
from expense_comparison import compare_saved
from policy import retirement_model_v340 as frozen

BASE={'decision_date':'2036-01-15','start_age':'54','investment_twd':'27000000','cash_twd':'2400000',
      'stock_bond':'70/30','cpi_2026':'110','decision_cpi':'125','decision_cpi_release':'2036-01-07','planned_extra_twd':'0'}
def item(y=2038,amount=1500000,cat='medical',basis='real_2026',price=None,key=None,title='醫療預留'):
    return {'id':key,'year':y,'category':cat,'amount_twd':amount,'basis':basis,'price_year':price,'title':title}
def browser_numbers(v):
    if isinstance(v,dict):return {k:browser_numbers(x) for k,x in v.items()}
    if isinstance(v,list):return [browser_numbers(x) for x in v]
    if isinstance(v,float) and v.is_integer():return int(v)
    return v

class Phase2Expenses(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();bridge.STATE_PATH=Path(self.tmp.name)/'record.json';workflow.INNER_DRAWS=256;bridge.initialize(None)
    def tearDown(self):self.tmp.cleanup()
    def op(self,name,data=None):return json.loads(bridge.dispatch(json.dumps({'op':name,'data':data or {}})))
    def save(self,e):return self.op('expense-schedule',{'action':'upsert','entry':e})
    def approve(self,**kw):return self.op('approve',dict(BASE,**kw))
    def test_crud_multiple_entries_before_initial_approval(self):
        self.save(item());self.save(item(2040,300000,cat='housing',title='購屋現金流'))
        values=bridge.ENGINE._state['expense_schedule']['entries'];self.assertEqual(len(values),2)
        e=dict(values[0],amount_twd=2000000);self.save(e)
        self.op('expense-schedule',{'action':'delete','entry':{'id':values[1]['id']}})
        self.assertEqual(bridge.ENGINE._state['expense_schedule']['entries'][0]['amount_twd'],2000000)
    def test_future_expense_changes_initial_required_assets(self):
        prior=self.approve()['data']['approval']['pos_pct'];bridge.initialize(None)
        self.save(item(2038,10000000,cat='housing',title='購屋'))
        now=self.approve()['data']['approval'];self.assertLess(now['pos_pct'],prior);self.assertEqual(now['extra_authorized_twd'],0)
        self.assertEqual(now['investment_open_twd'],27000000)
    def test_current_scheduled_and_ad_hoc_each_once(self):
        self.save(item(2036,1100000));r=self.approve(planned_extra_twd='200000')['data']['approval']
        self.assertAlmostEqual(r['extra_authorized_twd'],1100000*125/110+200000,delta=.01)
        lines=r['large_expense_sources']['items'];self.assertEqual(len(lines),2)
        self.assertAlmostEqual(sum(x['total_twd'] for x in lines),r['extra_authorized_twd'],delta=.03)
    def test_nominal_due_year_is_exact_and_future_is_disclosed_scenario(self):
        self.save(item(2036,1500000,basis='nominal_year',price=2036));r=self.approve()['data']['approval']
        self.assertAlmostEqual(r['extra_authorized_twd'],1500000,delta=.01)
        self.assertEqual(bridge.ENGINE._state['years'][0]['large_expense_snapshot']['resolved'][0]['conversion_source'],'SAVED_DECISION_CPI')
        self.save(item(2040,2000000,basis='nominal_year',price=2040,title='後續醫療'))
        view=bridge.ENGINE.overview()['expense_schedule'];future=[x for x in view['resolved'] if x['year']==2040][0]
        self.assertEqual(future['conversion_source'],'EXPLICIT_INFLATION_SCENARIO');self.assertAlmostEqual(future['nominal_due_twd'],2000000)
    def test_2026_real_cpi_conversion(self):
        self.save(item(2036,1100000));r=self.approve()['data']['approval'];self.assertAlmostEqual(r['extra_authorized_twd'],1250000)
    def test_nominal_2026_uses_known_reference_not_reverse_forecast(self):
        self.save(item(2036,1100000,basis='nominal_year',price=2026))
        r=self.approve()['data']['approval'];self.assertAlmostEqual(r['extra_authorized_twd'],1250000)
    def test_year_end_cpi_anchors_future_nominal_and_current_decision_overrides(self):
        self.save(item(2037,1500000,basis='nominal_year',price=2037));self.approve()
        closing=self.op('demo-close')['data'];closing['closing_cpi']='150';self.op('close',closing)
        item_=bridge.ENGINE.overview()['expense_schedule']['resolved'][0]
        self.assertAlmostEqual(item_['real_2026_twd'],1100000)
        r=self.approve(decision_date='2037-01-15',decision_cpi='132',decision_cpi_release='2037-01-07')['data']['approval']
        self.assertAlmostEqual(r['extra_authorized_twd'],1500000,delta=.01)
    def test_past_display_uses_approval_snapshot_after_inflation_change(self):
        self.save(item(2036,1000000,basis='nominal_year',price=2040));self.approve()
        before=bridge.ENGINE.overview()['expense_schedule']['resolved'][0]
        self.op('expense-schedule',{'action':'inflation','entry':{'inflation_pct':10}})
        self.assertEqual(before,bridge.ENGINE.overview()['expense_schedule']['resolved'][0])
    def test_no_schedule_keeps_original_approval_exact(self):
        plain=self.approve()['record']['years'][0];bridge.initialize(None)
        self.op('expense-schedule',{'action':'inflation','entry':{'inflation_pct':2}})
        unchanged=self.approve()['record']['years'][0];self.assertEqual(plain,unchanged)
    def test_default_car_duplicate_rejected_before_mutating_approval(self):
        self.save(item(2042,1200000,cat='car',title='購車'))
        old=bridge.STATE_PATH.read_bytes()
        with self.assertRaisesRegex(workflow.InputError,'定期換車'):self.approve()
        self.assertEqual(bridge.STATE_PATH.read_bytes(),old);self.assertIsNone(bridge.ENGINE._state['plan'])
    def test_duplicate_default_car_by_title_other_category(self):
        self.approve();old=bridge.STATE_PATH.read_bytes()
        with self.assertRaisesRegex(workflow.InputError,'定期換車'):self.save(item(2042,1200000,cat='other',title='換車'))
        self.assertEqual(bridge.STATE_PATH.read_bytes(),old)
    def test_exact_duplicate_and_double_manual_car_rejected(self):
        self.save(item())
        with self.assertRaisesRegex(workflow.InputError,'重複'):self.save(item())
        self.save(item(2039,1000000,cat='car',title='購車'))
        with self.assertRaisesRegex(workflow.InputError,'手動購車'):self.save(item(2039,2000000,cat='car',title='第二筆'))
    def test_invalid_inputs_atomic(self):
        for field,value in [('year','2038.5'),('amount_twd',float('nan')),('amount_twd',-1),('amount_twd',0),('category','rent'),('basis','unknown'),('amount_twd',True)]:
            e=item();e[field]=value
            with self.assertRaises(workflow.InputError):self.save(e)
            self.assertFalse(bridge.ENGINE._state['years'])
    def test_approved_year_locked_and_future_edit_preserves_old_snapshot(self):
        self.save(item(2036,100000));self.save(item());self.approve()
        old=copy.deepcopy(bridge.ENGINE._state['years']);values=bridge.ENGINE._state['expense_schedule']['entries']
        with self.assertRaisesRegex(workflow.InputError,'已核准'):self.op('expense-schedule',{'action':'delete','entry':{'id':values[0]['id']}})
        self.save(dict(values[1],amount_twd=3000000));self.assertEqual(old,bridge.ENGINE._state['years'])
    def test_end_of_horizon_and_first_year_limits(self):
        self.approve()
        for y in (2035,2087):
            with self.assertRaisesRegex(workflow.InputError,'104|已核准'):self.save(item(y))
        self.save(item(2086));self.assertEqual(bridge.ENGINE.overview()['expense_schedule']['resolved'][0]['age'],104)
    def test_future_schedule_survives_close_and_charged_next_year_once(self):
        self.save(item(2037,1100000));self.approve();self.op('close',self.op('demo-close')['data'])
        r=self.approve(decision_date='2037-01-15',decision_cpi='132',decision_cpi_release='2037-01-07')['data']['approval']
        self.assertAlmostEqual(r['extra_authorized_twd'],1320000,delta=.01);self.assertEqual(r['car_authorized_twd'],0)
        self.assertEqual(len(r['large_expense_sources']['items']),1)
    def test_import_new_schedule_and_old_without_schedule(self):
        self.save(item());self.approve();data=self.op('export')['data'];bridge.initialize(None)
        self.op('import',data);self.assertEqual(len(bridge.ENGINE._state['expense_schedule']['entries']),1)
        legacy=copy.deepcopy(data);legacy['payload'].pop('expense_schedule');legacy['payload']['years'][0].pop('large_expense_snapshot');legacy['sha256']=workflow.digest(legacy['payload'])
        self.op('import',legacy);self.assertNotIn('expense_schedule',bridge.ENGINE._state)
    def test_tampered_snapshot_even_rehashed_is_rejected(self):
        self.save(item(2036,100000));self.approve();b=self.op('export')['data'];old=bridge.STATE_PATH.read_bytes()
        s=b['payload']['years'][0]['large_expense_snapshot'];s['resolved'][0]['activation_real_m']+=1;s['sha256']=large.digest({k:v for k,v in s.items() if k!='sha256'});b['sha256']=workflow.digest(b['payload'])
        with self.assertRaisesRegex(workflow.InputError,'快照'):self.op('import',b)
        self.assertEqual(old,bridge.STATE_PATH.read_bytes())
    def test_backdated_edit_in_backup_or_wrong_allocation_rejected(self):
        self.save(item(2036,100000));self.approve();b=self.op('export')['data']
        bad=copy.deepcopy(b);bad['payload']['expense_schedule']['entries'][0]['amount_twd']+=1;bad['sha256']=workflow.digest(bad['payload'])
        with self.assertRaisesRegex(workflow.InputError,'回溯'):self.op('import',bad)
        bad=copy.deepcopy(b);bad['payload']['plan']['stock_weight']=.65;bad['sha256']=workflow.digest(bad['payload'])
        with self.assertRaisesRegex(workflow.InputError,'比例'):self.op('import',bad)
    def test_schedule_backup_before_retirement_is_accepted(self):
        self.save(item());b=self.op('export')['data'];bridge.initialize(None);self.op('import',b)
        self.assertEqual(len(bridge.ENGINE._state['expense_schedule']['entries']),1)
    def test_browser_numeric_roundtrip_snapshot(self):
        self.save(item(2036,100000));self.approve();b=browser_numbers(self.op('export')['data'])
        self.op('import',b)
    def test_original_legacy_backup_digest_still_accepted(self):
        self.approve();b=self.op('export')['data'];b.pop('sha256_contract');b['sha256']=workflow.legacy_digest(b['payload'])
        before=copy.deepcopy(b['payload']['years']);self.op('import',b);self.assertEqual(before,bridge.ENGINE._state['years'])
    def test_empty_schedule_pairing_is_exact_for_both_allocations(self):
        self.approve();s=copy.deepcopy(bridge.ENGINE._state);r=compare_saved(s,paths=256,inner_paths=128)
        self.assertEqual(s,bridge.ENGINE._state)
        for pair in (r['rows'][:2],r['rows'][2:]):self.assertEqual(pair[0]['diagnostics'],pair[1]['diagnostics'])
    def test_paired_large_housing_outflow_and_currency_units(self):
        self.save(item(2038,20000000,cat='housing',title='購屋'));self.approve();r=compare_saved(bridge.ENGINE._state,paths=256,inner_paths=128)
        for pair in (r['rows'][:2],r['rows'][2:]):
            self.assertLess(pair[1]['diagnostics']['plan_success'],pair[0]['diagnostics']['plan_success'])
            self.assertGreater(pair[1]['diagnostics']['first_gap_rate'],pair[0]['diagnostics']['first_gap_rate'])
        self.assertEqual(r['origin'],'FULL_YEAR_COUNTERFACTUAL_PRE_APPROVAL')
    def test_pending_projection_does_not_charge_first_schedule_twice(self):
        self.save(item(2036,1100000));self.save(item(2037,2200000,title='第二年醫療'));self.approve();s=copy.deepcopy(bridge.ENGINE._state)
        r=project_saved(s,paths=256,inner_paths=128)
        self.assertAlmostEqual(r['years'][0]['extra_paid_median_m'],1.25);self.assertAlmostEqual(r['years'][1]['extra_paid_median_m'],2.5)
        self.assertEqual(s,bridge.ENGINE._state)
    def test_actual_shortfall_separates_floor_and_mandatory_and_cash(self):
        cfg=frozen.ModelConfig(start_age=90,end_age=92,initial_investment=1,initial_safety_cash=.1,emergency_once=False,extra_mandatory_expense_by_age={90:5})
        r=trace_paths(cfg,engine=frozen,paths=256,inner_paths=128,injected_returns=(np.zeros((256,3)),np.zeros((256,3))))
        self.assertEqual(r['diagnostics']['first_mandatory_age_p50'],90);self.assertEqual(r['diagnostics']['first_floor_age_p50'],91)
        self.assertGreater(r['diagnostics']['first_gap_amount_median_m'],0);self.assertEqual(r['diagnostics']['first_gap_cash_after_median_m'],0)
        self.assertLess(r['diagnostics']['max_reconciliation_error_m'],1e-8)
    def test_first_gap_absent_is_null(self):
        cfg=frozen.ModelConfig(start_age=100,end_age=104,initial_investment=1000,emergency_once=False)
        r=trace_paths(cfg,engine=frozen,paths=256,inner_paths=128,injected_returns=(np.zeros((256,5)),np.zeros((256,5))))
        self.assertIsNone(r['diagnostics']['first_gap_age_p50']);self.assertIsNone(r['diagnostics']['first_gap_amount_median_m'])

if __name__=='__main__':unittest.main()
