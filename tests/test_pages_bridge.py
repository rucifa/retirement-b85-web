"""Browser-Pyodide transport tests using actual B85 engine; no fake return algorithm."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bridge,workflow

OPEN={'decision_date':'2036-01-15','start_age':'54','investment_twd':'27000000','cash_twd':'2400000','stock_bond':'70/30','cpi_2026':'110','decision_cpi':'125','decision_cpi_release':'2036-01-10','planned_extra_twd':'0'}
class PagesBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        bridge.STATE_PATH=Path(self.tmp.name)/'user_data'/'annual_records.json'
        workflow.INNER_DRAWS=256
        self.assertFalse(bridge.initialize(None)['has_data'])
    def tearDown(self):self.tmp.cleanup()
    def invoke(self,op,data=None):return json.loads(bridge.dispatch(json.dumps({'op':op,'data':data or {}},ensure_ascii=False)))
    def approve(self):return self.invoke('approve',OPEN)
    def test_pages_matches_actual_engine_policy_budget(self):
        r=self.approve();self.assertGreaterEqual(r['data']['approval']['living_authorized_twd'],500000*125/110);self.assertLessEqual(r['data']['approval']['living_authorized_twd'],715000*125/110)
        self.assertEqual(r['record']['plan']['fx_assumption'],30)
        self.assertFalse(r['data']['overview']['policy_active'])
    def test_year_end_and_next_year_and_browser_reload(self):
        a=self.approve();self.assertTrue(a['record']['years'])
        d=self.invoke('demo-close')['data'];closed=self.invoke('close',d)
        self.assertEqual(closed['data']['year_close']['status'],'CLOSED')
        self.assertAlmostEqual(closed['data']['year_close']['closing']['net_real_portfolio_return_pct'],5,2)
        snapshot=json.dumps(closed['record'],ensure_ascii=False)
        reloaded=bridge.initialize(snapshot)
        self.assertEqual(reloaded['years'][0]['status'],'CLOSED')
        next_=self.invoke('approve',{'decision_date':'2037-01-15','decision_cpi':'126.3','decision_cpi_release':'2037-01-10','planned_extra_twd':0})
        self.assertEqual(next_['data']['approval']['age'],55)
    def test_no_future_cpi_or_duplicate_approval(self):
        with self.assertRaisesRegex(workflow.InputError,'晚於使用日期'):
            bad=dict(OPEN,decision_cpi_release='2036-01-16');self.invoke('approve',bad)
        self.approve()
        with self.assertRaisesRegex(workflow.InputError,'尚未結算'):self.approve()
    def test_reimport_preserves_records_with_sha_and_can_continue(self):
        self.approve();b=self.invoke('export')['data'];self.assertEqual(b['sha256'],workflow.digest(b['payload']))
        bridge.initialize(None)
        recovered=self.invoke('import',b)
        self.assertEqual(recovered['data']['years'][0]['age'],54)
        self.assertEqual(recovered['record']['years'][0]['approval']['opening']['year'],2036)
        r=self.invoke('demo-close')['data'];self.invoke('close',r)
    def test_tampered_export_rejected_and_state_preserved(self):
        self.approve();b=self.invoke('export')['data'];old=bridge.STATE_PATH.read_bytes()
        b['payload']['years'][0]['approval']['opening']['investment_m']=999
        with self.assertRaisesRegex(workflow.InputError,'SHA256'):self.invoke('import',b)
        self.assertEqual(old,bridge.STATE_PATH.read_bytes())
    def test_different_fx_30_policy_rejected_even_with_rehashed_file(self):
        self.approve();b=self.invoke('export')['data'];b['payload']['plan']['fx_assumption']=31;b['sha256']=workflow.digest(b['payload'])
        with self.assertRaisesRegex(workflow.InputError,'不同政策'):self.invoke('import',b)
    def test_annual_jump_in_restored_snapshot_rejected(self):
        self.approve();b=self.invoke('export')['data'];b['payload']['years'][0]['approval']['opening']['year']=2037;b['sha256']=workflow.digest(b['payload'])
        with self.assertRaisesRegex(workflow.InputError,'跳號'):self.invoke('import',b)
    def test_reset_requires_confirmation_and_backup_is_exportable(self):
        self.approve();e=self.invoke('export')['data']
        with self.assertRaises(workflow.InputError):self.invoke('reset',{'confirm':'delete'})
        out=self.invoke('reset',{'confirm':'清除演練'})
        self.assertFalse(out['data']['has_data']);self.assertEqual(e['payload']['years'][0]['approval']['opening']['age'],54)
    def test_sensitive_cases_do_not_autocomplete(self):
        self.approve();d=self.invoke('demo-close')['data'];d['emergency_paid_twd']=1200000
        with self.assertRaisesRegex(workflow.InputError,'緊急支出'):self.invoke('close',d)
    def test_web_source_contains_no_third_party_financial_transfer(self):
        js=(ROOT/'static/app.js').read_text('utf-8');worker=(ROOT/'pyodide-worker.js').read_text('utf-8')
        html=(ROOT/'index.html').read_text('utf-8')
        self.assertIn('indexedDB',js);self.assertIn('request(\'/api/import\'',js)
        self.assertIn('pyodide',worker.lower());self.assertIn('年度',html)
        self.assertNotIn('api.github.com',worker);self.assertNotIn('cloudinary',js)
        self.assertNotIn('token=',worker)

if __name__=='__main__':unittest.main()
