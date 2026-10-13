import copy,json,tempfile,unittest
from pathlib import Path
import execution_planning as execution
import bridge,workflow
from test_phase2_expenses import BASE,browser_numbers

def annual():
    return {'approval_id':'test-approval','year':2036,'decision_date':'2036-01-15','investment_open_twd':10000000,
            'withdrawal_sources':{'status':'RECONCILED','total':{'invest_twd':2000000,'cash_twd':300000},'cash_refill_transfer_twd':500000}}
def holdings(usd=False):
    return [{'ticker':name,'broker':'測試券商','sleeve':sleeve,'currency':'USD' if usd else 'TWD',
            'units':qty,'price':100,'lot_step':1,'quote_date':'2036-01-15'}
            for name,sleeve,qty in [('STOCK','stock',70000),('BOND','bond',30000)]]
def payload(usd=False):return {'asof_date':'2036-01-15','fx_twd_per_usd':30 if usd else '',
                             'broker_cash_twd':'','fee_estimate_twd':'','holdings':holdings(usd)}

class ExecutionTests(unittest.TestCase):
    def test_sell_plan_covers_spending_plus_refill_without_double_counting(self):
        p,s=execution.prepare(payload(),annual(),{'stock_weight':.7})
        self.assertEqual(p['total_invest_liquidity_needed_twd'],2500000)
        self.assertEqual(p['estimated_net_sell_twd'],2500000)
        self.assertEqual(p['safety_cash_for_spending_twd'],300000)
        self.assertAlmostEqual(p['estimated_after_stock_weight'],.7)
        self.assertEqual(p['mode'],'PLANNING_ONLY_NO_TRANSACTIONS');self.assertNotIn('executed',p)
    def test_broker_cash_reduces_needed_sale_and_fees_are_only_cash_estimate(self):
        data=payload();data.update(broker_cash_twd=1000000,fee_estimate_twd=1000)
        p,_=execution.prepare(data,annual(),{'stock_weight':.7})
        self.assertGreaterEqual(p['estimated_net_sell_twd']+1000000,2500000)
        self.assertEqual(p['estimated_fees_twd'],1000)
    def test_cash_alone_requires_no_sales_or_fee(self):
        data=payload();data.update(broker_cash_twd=3000000,fee_estimate_twd=1000)
        p,_=execution.prepare(data,annual(),{'stock_weight':.7})
        self.assertEqual(p['estimated_gross_sell_twd'],0);self.assertEqual(p['estimated_fees_twd'],0)
    def test_cash_covered_needs_no_invented_holdings(self):
        data=payload();data.update(broker_cash_twd=2500000,holdings=[])
        p,_=execution.prepare(data,annual(),{'stock_weight':.7})
        self.assertEqual(p['orders'],[]);self.assertEqual(p['liquidity_shortfall_twd'],0);self.assertFalse(p['holdings_provided'])
    def test_missing_positions_when_sale_required_rejected(self):
        data=payload();data['holdings']=[]
        with self.assertRaisesRegex(ValueError,'不會猜測'):execution.prepare(data,annual(),{'stock_weight':.7})
    def test_different_configuration_changes_sale_allocation(self):
        a,_=execution.prepare(payload(),annual(),{'stock_weight':.7});b,_=execution.prepare(payload(),annual(),{'stock_weight':.65})
        self.assertGreater(b['orders'][0]['sell_units'],a['orders'][0]['sell_units'])
        self.assertAlmostEqual(b['estimated_after_stock_weight'],.65)
    def test_usd_fx_must_be_supplied_not_assumed(self):
        data=payload(True);data['fx_twd_per_usd']=''
        with self.assertRaises(ValueError):execution.prepare(data,annual(),{'stock_weight':.7})
        data['fx_twd_per_usd']=32;p,_=execution.prepare(data,annual(),{'stock_weight':.7})
        self.assertEqual(p['orders'][0]['price_twd'],3200)
    def test_fractional_units_and_upward_rounding(self):
        data=payload();data['holdings'][0].update(units=2.12345,lot_step=.00001,price=1000000.1234)
        p,_=execution.prepare(data,annual(),{'stock_weight':.7})
        self.assertLessEqual(p['orders'][0]['sell_units'],2.12345);self.assertGreaterEqual(p['liquidity_shortfall_twd'],0)
    def test_sale_never_exceeds_units_and_insufficient_fails_honestly(self):
        data=payload()
        for h in data['holdings']:h['units']=.25
        p,_=execution.prepare(data,annual(),{'stock_weight':.7})
        self.assertEqual(p['status'],'INSUFFICIENT_QUOTED_HOLDINGS');self.assertGreater(p['liquidity_shortfall_twd'],0)
        self.assertTrue(all(h['sell_units']<=h['units'] for h in p['orders']))
    def test_quote_dates_and_wrong_approval_rejected(self):
        for key,value in [('asof_date','2035-01-01'),('approval_id','wrong')]:
            data=payload();data[key]=value
            with self.assertRaises(ValueError):execution.prepare(data,annual(),{'stock_weight':.7})
        data=payload();data['holdings'][0]['quote_date']='2036-01-16'
        with self.assertRaisesRegex(ValueError,'報價日期'):execution.prepare(data,annual(),{'stock_weight':.7})
    def test_duplicate_positions_nan_and_bool_rejected(self):
        data=payload();data['holdings'].append(copy.deepcopy(data['holdings'][0]))
        with self.assertRaisesRegex(ValueError,'重複'):execution.prepare(data,annual(),{'stock_weight':.7})
        for key,value in [('units',float('nan')),('price',-1),('lot_step',True)]:
            data=payload();data['holdings'][0][key]=value
            with self.assertRaises(ValueError):execution.prepare(data,annual(),{'stock_weight':.7})
    def test_unknown_source_prevents_guessing_sale(self):
        y=annual();y['withdrawal_sources']['status']='UNAVAILABLE_REQUIRES_REVIEW'
        with self.assertRaisesRegex(ValueError,'核准來源'):execution.prepare(payload(),y,{'stock_weight':.7})
    def test_saved_planning_roundtrip_does_not_change_approval_or_balances(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge.STATE_PATH=Path(temp)/'record.json';workflow.INNER_DRAWS=128;bridge.initialize(None)
            def op(name,data=None):return json.loads(bridge.dispatch(json.dumps({'op':name,'data':data or {}})))
            op('approve',BASE);before=copy.deepcopy(bridge.ENGINE._state['years']);data=payload();data['holdings']=holdings(True);data['fx_twd_per_usd']=30
            r=op('execution-plan',data);self.assertEqual(before,bridge.ENGINE._state['years'])
            self.assertEqual(r['data']['planning']['mode'],'PLANNING_ONLY_NO_TRANSACTIONS')
            b=browser_numbers(op('export')['data']);op('import',b)
            self.assertEqual(before,bridge.ENGINE._state['years'])
            self.assertEqual(len(bridge.ENGINE._state['execution_plans']),1)
    def test_cannot_restore_planning_as_executed_or_foreign_approval(self):
        _,saved=execution.prepare(payload(),annual(),{'stock_weight':.7})
        r={'years':[{'approval':{'approval_id':'test-approval'}}],'execution_plans':{'test-approval':saved}}
        execution.validate_saved_plans(r)
        bad=copy.deepcopy(r);bad['execution_plans']['test-approval']['mode']='EXECUTED'
        with self.assertRaisesRegex(ValueError,'已執行'):execution.validate_saved_plans(bad)

if __name__=='__main__':unittest.main()
