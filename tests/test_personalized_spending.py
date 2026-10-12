"""Personalized spending research parity and safety: real B+85 fork, no fake PoS."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bridge,workflow,spending_profile as profile

BASE={"decision_date":"2036-01-15","start_age":"65","investment_twd":"27000000",
      "cash_twd":"2400000","stock_bond":"70/30","cpi_2026":"110",
      "decision_cpi":"125","decision_cpi_release":"2036-01-10","planned_extra_twd":"0"}
def personal(normal=650000,core=600000,floor=500000):
    return dict(BASE,spending_profile_mode=profile.MODE,
      normal_spend_2026_twd=str(normal),core_spend_2026_twd=str(core),
      floor_spend_2026_twd=str(floor))
class PersonalizedSpendingTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory()
    bridge.STATE_PATH=Path(self.tmp.name)/"record.json"
    workflow.INNER_DRAWS=256
    bridge.initialize(None)
 def tearDown(self):self.tmp.cleanup()
 def op(self,name,data=None):
    return json.loads(bridge.dispatch(json.dumps({"op":name,"data":data or {}},ensure_ascii=False)))
 def test_original_profile_does_not_alter_b85_parity(self):
    legacy=self.op("approve",BASE)["data"]["approval"]
    bridge.initialize(None)
    research=self.op("approve",personal())["data"]["approval"]
    self.assertEqual(research["spending_profile_mode"],profile.MODE)
    for k in ("pos_pct","sticky_after","living_authorized_twd","normal_reference_twd","floor_reference_twd",
              "car_authorized_twd","bridge_from_cash_twd","cash_refill_twd"):
       self.assertAlmostEqual(legacy[k],research[k],delta=.1,msg=k)
    self.assertEqual(research["core_reference_twd"],round(600000*125/110,2))
 def test_different_users_change_model_pos_and_withdrawals(self):
    low=self.op("approve",personal(360000,300000,240000))["data"]["approval"]
    bridge.initialize(None)
    high=self.op("approve",personal(1600000,1400000,1200000))["data"]["approval"]
    self.assertLess(low["normal_reference_twd"],high["normal_reference_twd"])
    self.assertLess(low["floor_reference_twd"],high["floor_reference_twd"])
    self.assertGreater(low["pos_pct"],high["pos_pct"])
    self.assertLess(low["living_authorized_twd"],high["living_authorized_twd"])
    self.assertAlmostEqual(low["normal_reference_twd"],360000*125/110,delta=.02)
    self.assertAlmostEqual(high["normal_reference_twd"],1600000*125/110,delta=.02)
 def test_core_only_reference_never_charges_twice(self):
    one=self.op("approve",personal(700000,620000,400000))["data"]["approval"]
    bridge.initialize(None)
    other=self.op("approve",personal(700000,480000,400000))["data"]["approval"]
    self.assertEqual(one["pos_pct"],other["pos_pct"])
    self.assertEqual(one["living_authorized_twd"],other["living_authorized_twd"])
    self.assertNotEqual(one["core_reference_twd"],other["core_reference_twd"])
 def test_reject_bad_order_and_invalid_amount_without_saving(self):
    for input_ in (personal(360000,400000,240000),
                   personal(500000,480000,600000),
                   personal("NaN",240000,120000),
                   personal(700000,"100.50",200000),
                   personal(15000000,600000,500000)):
       with self.assertRaises(workflow.InputError):self.op("approve",input_)
       self.assertFalse(self.op("state")["data"]["has_data"])
 def test_profile_locked_through_export_import_and_next_year(self):
    first=self.op("approve",personal(800000,720000,560000))
    plan=first["record"]["plan"]
    self.assertEqual(plan["model_version"],"research_personalized_spending_v1")
    self.assertEqual(plan["spending_profile"]["normal_twd"],800000)
    self.assertEqual(plan["spending_profile_sha256"],profile.digest(plan["spending_profile"]))
    exp=self.op("export")["data"]
    bridge.initialize(None)
    rest=self.op("import",exp)
    self.assertEqual(rest["data"]["years"][0]["spending_profile_2026_real"]["floor_twd"],560000)
    self.op("close",self.op("demo-close")["data"])
    second=self.op("approve",{"decision_date":"2037-01-15","decision_cpi":"126",
                   "decision_cpi_release":"2037-01-10","planned_extra_twd":"0"})["data"]["approval"]
    self.assertEqual(second["spending_profile_mode"],profile.MODE)
    self.assertFalse(second["calendar_first_year"])
 def test_tamper_profile_even_if_json_digest_recomputed(self):
    self.op("approve",personal(750000,650000,550000))
    exp=self.op("export")["data"]
    exp["payload"]["plan"]["spending_profile"]["normal_twd"]=900000
    exp["sha256"]=workflow.digest(exp["payload"])
    with self.assertRaisesRegex(workflow.InputError,"個人化"):self.op("import",exp)
    self.assertEqual(self.op("state")["data"]["years"][0]["spending_profile_2026_real"]["normal_twd"],750000)
 def test_short_calendar_year_scales_personal_budget(self):
    args=personal(850000,650000,470000)
    args.update(decision_date="2036-10-12",decision_cpi_release="2036-10-07")
    a=self.op("approve",args)["data"]["approval"]
    self.assertEqual((a["calendar_days"],a["calendar_year_days"]),(81,366))
    self.assertAlmostEqual(a["living_authorized_twd"],
      a["full_year_living_reference_twd"]*81/366,delta=.03)

if __name__=="__main__":unittest.main()
