import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import workflow,bridge
from expense_contract import bind_current_expense,CONTRACT
from policy import personalized_research_engine as model
from policy.personalized_research_annual import AnnualInput,decide_year
from capacity_research import _capital_capacity,_validation


class ExpenseContractTests(unittest.TestCase):
    def setUp(self):
        self.cfg=model.ModelConfig(start_age=65,end_age=104,stock_weight=.7,
            floor_spend=.4,personalized_normal_spend=.7,personalized_core_spend=.6,
            use_charity=False,use_prosperity=True,prosperity_spending_mode='recommended_target',
            friction=model.FRICTIONS['net_central_2026ref'])
    def run_year(self,extra,investment=22.,cash=2.4,age=65,sticky=1.,prev=None):
        return decide_year(AnnualInput(decision_date='2026-01-01',age=age,
            retirement_start_age=65,investment_start_m=investment,safety_cash_start_m=cash,
            sticky_before=sticky,emergency_pending=True,extra_mandatory_m=extra,
            previous_completed_real_portfolio_return=prev),self.cfg,n_inner=4096,seed=20261011)
    def test_known_extra_crosses_guardrail_and_bridge_once(self):
        before,after=self.run_year(0),self.run_year(1.5)
        self.assertGreater(before.pos,.75);self.assertLess(after.pos,.75)
        self.assertEqual(after.sticky_after,.9)
        self.assertAlmostEqual(after.bridge_from_cash_m,.315)
        self.assertEqual(after.cash_refill_m,0)
        self.assertEqual(after.extra_mandatory_paid_m,1.5)
        self.assertAlmostEqual(after.investment_before_return_m+after.safety_cash_before_return_m,
            24.4-.63-1.5)
    def test_pos_matches_independent_distribution_and_extra_monotonicity(self):
        previous=1
        for extra in (0,.1,1.5,3):
            result=self.run_year(extra)
            cfg=replace(self.cfg,extra_mandatory_expense_by_age={65:extra})
            reference=model.RequiredAssetCache(cfg,4096,20261011).probability_of_success(24.4,65,1,True)
            self.assertEqual(result.pos,reference)
            self.assertLessEqual(result.pos,previous);previous=result.pos
    def test_normal_recovery_pos_uses_same_known_extra(self):
        r=self.run_year(1.5,investment=27,age=66,sticky=.8,prev=.05)
        reference=model.single_state_pos(29.4,66,1,True,
            bind_current_expense(self.cfg,66,1.5),n_inner=4096,seed=20261011)
        self.assertIsNotNone(r.normal_pos);self.assertEqual(r.normal_pos,reference)
    def test_cash_refill_transfer_cap_and_no_proactive_bridge_below_reserve(self):
        r=self.run_year(1.,investment=40,cash=1.)
        self.assertGreater(r.pos,.75);self.assertEqual(r.bridge_from_cash_m,0)
        self.assertEqual(r.cash_refill_m,.5);self.assertAlmostEqual(r.reconciliation_error_m,0)
        r=self.run_year(0.,investment=3,cash=1.)
        self.assertEqual(r.bridge_from_cash_m,0);self.assertEqual(r.cash_refill_m,0)
    def test_binding_is_immutable_idempotent_and_conflict_rejected(self):
        before=copy.deepcopy(self.cfg)
        first=bind_current_expense(self.cfg,65,1.5)
        self.assertEqual(bind_current_expense(first,65,1.5).extra_mandatory_expense_by_age,{65:1.5})
        self.assertEqual(self.cfg,before)
        with self.assertRaises(ValueError):bind_current_expense(first,65,2.)
    def test_capacity_and_independent_outer_share_extra(self):
        baseline=_capital_capacity(self.cfg,22,2.4,paths=256,seed=20261011)
        extra=_capital_capacity(self.cfg,22,2.4,paths=256,seed=20261011,planned_extra_m=1.5)
        self.assertTrue((extra<=baseline).all())
        r=_validation(self.cfg,700000,.4,22,2.4,paths=256,inner=128,seed=20261031,planned_extra_m=1.5)
        cfg=bind_current_expense(replace(self.cfg,initial_investment=22,initial_safety_cash=2.4),65,1.5)
        expected=model.simulate_outer(cfg,n_outer=256,n_inner=128,seed=20261031)
        self.assertEqual(r['model_full_policy_success'],round(expected['success'],6))

if __name__=='__main__':unittest.main()
