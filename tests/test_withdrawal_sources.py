"""P0 annual approval source attribution: full parity and fail-closed cases."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import bridge
import workflow
from withdrawal_sources import attribution, CONTRACT


def sample(inv,cash,living,bridge,car,extra,refill,after_inv,after_cash):
    o=SimpleNamespace(investment_m=inv,safety_cash_m=cash)
    p=SimpleNamespace(living_pool_paid_m=living,bridge_from_cash_m=bridge,
        car_paid_m=car,extra_mandatory_paid_m=extra,cash_refill_m=refill,
        investment_before_return_m=after_inv,safety_cash_before_return_m=after_cash,
        cash_bridge_reserve_m=1.2)
    return SimpleNamespace(opening=o,policy_preview=p)


class WithdrawalSourceTests(unittest.TestCase):
    def test_investment_first_and_bridge_not_double_counted(self):
        row=attribution(sample(10,2.4,.65,.3,1.2,.1,.5,7.85,2.6),100,100)
        self.assertEqual(row["contract"],CONTRACT)
        self.assertEqual(row["status"],"RECONCILED")
        self.assertAlmostEqual(row["living"]["invest_twd"],350000)
        self.assertAlmostEqual(row["living"]["cash_twd"],300000)
        self.assertAlmostEqual(row["car"]["invest_twd"],1200000)
        self.assertAlmostEqual(row["extra"]["invest_twd"],100000)
        self.assertAlmostEqual(row["total"]["total_twd"],1950000)
        self.assertAlmostEqual(row["bridge_twd"],300000)
        self.assertAlmostEqual(row["cash_refill_transfer_twd"],500000)
        self.assertAlmostEqual(row["investment_after_approval_twd"],7850000)
        self.assertAlmostEqual(row["cash_after_approval_twd"],2600000)

    def test_insufficient_investments_car_uses_cash_as_existing_policy(self):
        row=attribution(sample(.4,2.4,.6,.1,.8,.2,0,0,1.2),100,100)
        self.assertEqual(row["status"],"RECONCILED")
        self.assertAlmostEqual(row["living"]["invest_twd"],400000)
        self.assertAlmostEqual(row["living"]["cash_twd"],200000)
        self.assertAlmostEqual(row["car"]["invest_twd"],0)
        self.assertAlmostEqual(row["car"]["cash_twd"],800000)
        self.assertAlmostEqual(row["extra"]["cash_twd"],200000)
        self.assertAlmostEqual(row["cash_after_approval_twd"],1200000)

    def test_unmatched_legacy_or_partial_proration_fails_closed(self):
        row=attribution(sample(.4,2.4,.6,.1,.8,.2,0,.2,1.),100,100)
        self.assertEqual(row["status"],"UNAVAILABLE_REQUIRES_REVIEW")
        self.assertNotIn("total",row)

    def test_cpi_conversion_and_zero_car(self):
        row=attribution(sample(10,2.4,.6,0,0,0,0,9.4,2.4),120,100)
        self.assertEqual(row["status"],"RECONCILED")
        self.assertEqual(row["car"]["total_twd"],0)
        self.assertEqual(row["living"]["invest_twd"],720000)
        self.assertEqual(row["total"]["total_twd"],720000)

    def test_real_saved_approval_without_mutating_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge.STATE_PATH=Path(tmp)/"record.json"
            workflow.INNER_DRAWS=256
            bridge.initialize(None)
            input_={"decision_date":"2036-10-12","start_age":"54",
                    "investment_twd":"27000000","cash_twd":"2400000",
                    "stock_bond":"70/30","cpi_2026":"110",
                    "decision_cpi":"125","decision_cpi_release":"2036-10-07",
                    "planned_extra_twd":"1500000"}
            out=json.loads(bridge.dispatch(json.dumps({"op":"approve","data":input_})))
            year=out["data"]["approval"]
            self.assertEqual(year["withdrawal_sources"]["status"],"RECONCILED")
            a=year["withdrawal_sources"]
            self.assertAlmostEqual(a["total"]["total_twd"],
                 year["living_authorized_twd"]+year["car_authorized_twd"]+
                 year["extra_authorized_twd"],delta=.04)
            self.assertAlmostEqual(a["investment_after_approval_twd"],
                 out["record"]["years"][0]["approval"]["policy_preview"]["investment_before_return_m"]*1e6*125/out["record"]["plan"]["activation_cpi"],delta=.04)
            self.assertNotIn("withdrawal_sources",out["record"]["years"][0])
            exported=json.loads(bridge.dispatch(json.dumps({"op":"export","data":{}})))["data"]
            self.assertEqual(exported["sha256"],workflow.digest(exported["payload"]))
            old=json.dumps(exported,ensure_ascii=False)
            bridge.initialize(None)
            restored=json.loads(bridge.dispatch(json.dumps({"op":"import","data":exported})))
            self.assertEqual(restored["data"]["years"][0]["withdrawal_sources"],a)
            self.assertEqual(old,json.dumps(exported,ensure_ascii=False))


if __name__=="__main__":
    unittest.main()
