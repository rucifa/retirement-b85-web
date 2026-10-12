import copy,json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
import bridge,workflow
from policy import personalized_research_engine as research,retirement_model_v340 as frozen
from projection_research import trace_paths,project_saved
from expense_contract import bind_current_expense

BASE={'decision_date':'2036-10-12','start_age':'65','investment_twd':'27000000',
      'cash_twd':'2400000','stock_bond':'70/30','cpi_2026':'110',
      'decision_cpi':'125','decision_cpi_release':'2036-10-07','planned_extra_twd':'1500000'}

class ProjectionResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();bridge.STATE_PATH=Path(self.tmp.name)/'record.json'
        workflow.INNER_DRAWS=256;bridge.initialize(None)
    def tearDown(self):self.tmp.cleanup()
    def op(self,name,data=None):return json.loads(bridge.dispatch(json.dumps({'op':name,'data':data or {}})))
    def test_frozen_and_research_exact_full_year_outer_parity(self):
        for engine in (research,frozen):
            for scenario in ('base','stress','conservative'):
                cfg=engine.ModelConfig(start_age=54,end_age=104,scenario=scenario,
                    use_charity=False,use_prosperity=True,prosperity_spending_mode='recommended_target',
                    friction=engine.FRICTIONS['net_central_2026ref'],extra_mandatory_expense_by_age={54:1.5})
                expected=engine.simulate_outer(cfg,n_outer=256,n_inner=128,seed=20261112)
                actual=trace_paths(cfg,engine=engine,paths=256,inner_paths=128,seed=20261112)
                for k in ('terminal_med','terminal_p10','terminal_p90','life_med','cash_bridge_med','ever_cash_bridge'):
                    self.assertAlmostEqual(actual['diagnostics'][k],expected[k],places=10,msg=k)
                self.assertEqual(actual['diagnostics']['plan_success'],expected['success'])
                self.assertLess(actual['diagnostics']['max_reconciliation_error_m'],1e-8)
    def test_pending_approval_spending_once_partial_year_and_read_only(self):
        self.op('approve',BASE);state=copy.deepcopy(bridge.ENGINE._state);before=bridge.STATE_PATH.read_bytes()
        cfg=workflow.policy_config(state['plan']);row=state['years'][-1];o=row['approval']['opening'];p=row['approval']['policy_preview']
        cfg=replace(cfg,emergency_once=False)
        cfg=bind_current_expense(cfg,65,o['planned_extra_m'])
        zero=np.zeros((256,40))
        trace=trace_paths(cfg,engine=frozen,paths=256,inner_paths=128,opening=o,locked=p,
            fraction=81/366,injected_returns=(zero,zero))
        self.assertAlmostEqual(trace['investment'][0,0],p['investment_before_return_m'])
        self.assertAlmostEqual(trace['cash'][0,0],p['safety_cash_before_return_m'])
        self.assertEqual(trace['annual'][0]['extra_paid_median_m'],1.5)
        self.assertEqual(trace['annual'][1]['extra_paid_median_m'],0)
        self.assertAlmostEqual(trace['annual'][5]['car_paid_median_m'],1.2*125/110)
        result=project_saved(state,paths=256,inner_paths=128)
        self.assertEqual(bridge.ENGINE._state,state);self.assertEqual(bridge.STATE_PATH.read_bytes(),before)
        self.assertEqual(result['first_calendar_fraction'],81/366)
        self.assertEqual(result['years'][-1]['age'],104)
    def test_percentiles_all_paths_units_and_nominal_inflation(self):
        self.op('approve',BASE);s=bridge.ENGINE._state
        r=project_saved(s,paths=256,inner_paths=128,inflation_pct=2)
        r0=project_saved(s,paths=256,inner_paths=128,inflation_pct=0)
        for row in r['years']:
            for asset in ('total','investment','cash'):
                q=row[asset+'_real_2026_twd'];self.assertTrue(0<=q[0]<=q[1]<=q[2])
        self.assertEqual(r['years'][0]['total_real_2026_twd'],r0['years'][0]['total_real_2026_twd'])
        j=4;self.assertAlmostEqual(r['years'][j]['total_nominal_twd'][1]/r0['years'][j]['total_nominal_twd'][1],1.02**(j+81/366))
        self.assertTrue(r['all_paths_included']);self.assertTrue(r['percentiles_are_not_pos'])
    def test_completed_ledger_continuity_sticky_and_emergency_not_reset(self):
        self.op('approve',BASE);self.op('close',self.op('demo-close')['data'])
        state=copy.deepcopy(bridge.ENGINE._state);r=project_saved(state,paths=256,inner_paths=128)
        self.assertEqual(r['years'][0]['year'],2037);self.assertEqual(r['start_age'],66)
        self.assertFalse(r['first_approval_locked']);self.assertEqual(state,bridge.ENGINE._state)
        self.assertEqual(r['years'][0]['extra_paid_median_m'],0)
    def test_failures_are_absorbing_and_actual_floor_checks_continue(self):
        cfg=frozen.ModelConfig(start_age=90,end_age=104,initial_investment=.1,initial_safety_cash=.1,
            emergency_once=False,use_charity=False)
        r=trace_paths(cfg,engine=frozen,paths=256,inner_paths=128,injected_returns=(np.zeros((256,15)),np.zeros((256,15))))
        self.assertEqual(r['diagnostics']['plan_success'],0);self.assertEqual(r['diagnostics']['lifetime_floor_success'],0)
        self.assertTrue((r['investment']==0).all());self.assertTrue((r['cash']==0).all())
    def test_constant_paths_coincide_and_extreme_returns_conserve(self):
        cfg=frozen.ModelConfig(start_age=90,end_age=104,emergency_once=False,use_charity=False)
        rp=np.full((256,15),.01);rc=np.zeros_like(rp);rp[:,0]=-1
        r=trace_paths(cfg,engine=frozen,paths=256,inner_paths=128,injected_returns=(rp,rc))
        self.assertTrue((r['investment']>=0).all());self.assertLess(r['diagnostics']['max_reconciliation_error_m'],1e-8)
        self.assertTrue((np.quantile(r['investment'],.1,axis=0)==np.quantile(r['investment'],.9,axis=0)).all())
    def test_reproducibility_different_seed_and_invalid_requests(self):
        self.op('approve',BASE);s=bridge.ENGINE._state
        a=project_saved(s,paths=256,inner_paths=128);b=project_saved(s,paths=256,inner_paths=128)
        self.assertEqual(a['years'],b['years'])
        c=project_saved(s,paths=256,inner_paths=128,seed=20261113);self.assertNotEqual(a['years'],c['years'])
        for args in ({'paths':0},{'paths':True},{'inner_paths':99999},{'inflation_pct':float('nan')}):
            with self.assertRaises(ValueError):project_saved(s,**args)
    def test_completed_104_no_future_and_start90_full_horizon(self):
        self.op('approve',dict(BASE,start_age='90'))
        r=self.op('projection',{'paths':256,'inner_paths':128})['data']
        self.assertEqual(len(r['years']),15)
        s=copy.deepcopy(bridge.ENGINE._state);s['years'][-1]['close']={'x':1}
        s['years'][-1]['approval']['opening']['age']=104
        s['years'][-1]['close']={'investment_next_m':1,'safety_cash_next_m':1,'sticky_next':1,'emergency_pending_next':False,'net_portfolio_real_return':0}
        with self.assertRaisesRegex(ValueError,'104'):project_saved(s,paths=256,inner_paths=128)

    def test_each_year_matches_real_scalar_annual_adapter_including_emergency(self):
        from policy.annual_execution_v340 import AnnualInput,decide_year
        cfg=frozen.ModelConfig(start_age=65,end_age=68,car_ages=(67,),
            forced_emergency_age=66,forced_emergency_amount=1.3,
            extra_mandatory_expense_by_age={65:1.5},use_charity=False,
            use_prosperity=True,prosperity_spending_mode='recommended_target')
        rp=np.full((256,4),.03);rc=np.zeros_like(rp)
        trace=trace_paths(cfg,engine=frozen,paths=256,inner_paths=128,injected_returns=(rp,rc))
        inv,cash,mult,pending=cfg.initial_investment,cfg.initial_safety_cash,1.,True
        for j,age in enumerate(range(65,69)):
            r=decide_year(AnnualInput(decision_date=f'{2026+j}-01-01',age=age,retirement_start_age=65,
                investment_start_m=inv,safety_cash_start_m=cash,sticky_before=mult,
                emergency_pending=pending,previous_completed_real_portfolio_return=.03 if j else None,
                extra_mandatory_m=cfg.extra_mandatory_expense_by_age.get(age,0.),
                emergency_event_m=1.3 if age==66 else 0.,realized_year_portfolio_return=.03),
                cfg,n_inner=128,seed=20261112)
            self.assertAlmostEqual(trace['investment'][0,j],r.investment_next_start_m,places=10)
            self.assertAlmostEqual(trace['cash'][0,j],r.safety_cash_next_start_m,places=10)
            inv,cash,mult,pending=r.investment_next_start_m,r.safety_cash_next_start_m,r.sticky_after,r.emergency_pending_next
        self.assertEqual(trace['annual'][1]['emergency_paid_median_m'],1.3)
        self.assertEqual(trace['annual'][2]['emergency_paid_median_m'],0.)
        self.assertEqual(trace['annual'][2]['car_paid_median_m'],1.2)

if __name__=='__main__':unittest.main()
