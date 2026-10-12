"""Run in the public B85 repo only after applying the research patch."""
import copy
import unittest
import numpy as np
from capacity_research import (
    _candidate, _lower_wilson, _capital_capacity,
    evaluate_saved_first_year, SEARCH_SEED,
)
from policy import personalized_research_engine as engine


class InverseCapacityTests(unittest.TestCase):
    def test_rank_and_floor_fail_closed(self):
        caps = np.array([.10,.20,.30,.40, .50, .60, .70, .80, .90, 1.00])
        self.assertEqual(_candidate(caps,.90,100_000),(200_000,'CAPACITY_CANDIDATE_ONLY'))
        self.assertEqual(_candidate(caps,.90,210_000),(None,'FLOOR_UNATTAINABLE_AT_TARGET'))
        self.assertLessEqual(_candidate(caps,.99,100_000)[0],_candidate(caps,.95,100_000)[0])

    def test_wilson_is_not_point_probability(self):
        self.assertLess(_lower_wilson(100,100), 1.)
        self.assertLess(_lower_wilson(97,100), .97)

    def test_required_asset_distribution_parity(self):
        cfg=engine.ModelConfig(start_age=65,end_age=104,stock_weight=.70,
            floor_spend=.40, personalized_normal_spend=.65,
            personalized_core_spend=.56, use_charity=False)
        paths=256
        capacities=_capital_capacity(cfg, 27., 2.4,paths=paths,seed=SEARCH_SEED)
        for n in (.40,.65,.9):
            candidate = engine.ModelConfig(start_age=65,end_age=104,stock_weight=.70,
                floor_spend=.40, personalized_normal_spend=n,
                personalized_core_spend=.40+(n-.40)*2/3, use_charity=False)
            independent=engine.RequiredAssetCache(candidate,paths,SEARCH_SEED)
            expected=independent.probability_of_success(29.4,65,1.0,True)
            observed=float(np.count_nonzero(capacities >= n)/paths)
            self.assertAlmostEqual(expected,observed,delta=1/paths+1e-10)

    def test_first_year_read_only_95_99(self):
        cfg={'start_age':65, 'stock_weight':.70, 'cpi_2026':111.5,
             'activation_cpi':112.8, 'spending_profile':{
                'schema':'SPENDING_PROFILE_2026_REAL_V1',
                'floor_twd':350_000, 'normal_twd':350_000, 'core_twd':350_000}}
        plan={'first_year':2026,'start_age':65,'stock_weight':.70,
              'cpi_2026':111.5,'activation_cpi':112.8,'spending_profile':cfg['spending_profile']}
        state={'plan':plan,'years':[{'approval':{'opening':{
               'decision_date':'2026-10-12','year':2026,'age':65,'start_age':65,
               'investment_m':27.0,'safety_cash_m':2.4,'planned_extra_m':0.,
               }},'cpi_decision':112.8}]}
        snapshot=copy.deepcopy(state)
        result=evaluate_saved_first_year(state,paths=256)
        self.assertEqual(state,snapshot)
        self.assertEqual(result['status'],'RESEARCH_CANDIDATE_NOT_A_SAFE_WITHDRAWAL')
        self.assertFalse(result['target_lifetime_mc_certified'])
        p95=result['results']['p95']; p99=result['results']['p99']
        if p95['normal_2026_real_twd'] is not None and p99['normal_2026_real_twd'] is not None:
            self.assertLessEqual(p99['normal_2026_real_twd'],p95['normal_2026_real_twd'])
        for r in (p95,p99):
            if r['normal_2026_real_twd'] is not None:
                self.assertGreaterEqual(r['normal_2026_real_twd'],350000)
                self.assertFalse(r['guardrail_cut_now'])


if __name__=='__main__':
    unittest.main()
