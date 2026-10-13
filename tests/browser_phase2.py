"""真正Chromium/Pyodide驗證多筆支出、對照研究、提款規劃與備份。"""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=await browser.new_context(accept_downloads=True)
        page=await context.new_page();page.set_default_timeout(180000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda d:asyncio.create_task(d.accept()))
        try:
            await page.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded')
            await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            for id in ['expense-year','expense-amount','expense-price-year','execution-asof','execution-fx','execution-broker-cash','execution-fee']:
                assert await page.locator('#'+id).input_value()==''
            for id in ['expense-year','expense-amount','expense-price-year']:
                assert await page.locator('#'+id).get_attribute('placeholder')
            async def schedule(year,amount,category='medical',basis='real_2026',price_year=None,title='醫療預留'):
                await page.locator('#expense-year').fill(str(year));await page.locator('#expense-amount').fill(str(amount))
                await page.locator('#expense-category').select_option(category);await page.locator('#expense-basis').select_option(basis)
                if price_year:await page.locator('#expense-price-year').fill(str(price_year))
                await page.locator('#expense-title-input').fill(title);await page.locator('#expense-save').click()
                await page.wait_for_function('!document.getElementById("expense-save").disabled')
            await schedule(2036,1500000,basis='nominal_year',price_year=2036)
            await schedule(2037,1100000,title='第二年醫療')
            await schedule(2041,12000000,category='housing',title='購屋現金流')
            assert await page.locator('#expense-schedule-list tbody tr').count()==3
            await schedule(2041,12000000,category='housing',title='購屋現金流')
            assert '重複' in await page.locator('#alert').inner_text()
            assert await page.locator('#expense-schedule-list tbody tr').count()==3
            # 修改、刪除與本機重新載入，尚無年度也可保存排程。
            await page.locator('[data-expense-edit]').last.click();await page.locator('#expense-amount').fill('10000000');await page.locator('#expense-save').click()
            await page.wait_for_function('!document.getElementById("expense-save").disabled')
            await page.reload();await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            assert await page.locator('#expense-schedule-list tbody tr').count()==3
            assert await page.evaluate("state.expense_schedule.entries.at(-1).amount_twd")==10000000
            data={'decision_date':'2036-01-15','start_age':'54','investment_twd':'27000000','cash_twd':'2400000',
                  'floor_spend_2026_twd':'500000','normal_spend_2026_twd':'650000','cpi_2026':'110',
                  'decision_cpi':'125','decision_cpi_release':'2036-01-07','planned_extra_twd':'200000'}
            await page.locator('details.cpi-manual-input summary').click()
            for id,value in data.items():await page.locator('#'+id).fill(value)
            await page.evaluate("document.getElementById('decision_cpi').dataset.autoSource='MANUAL'")
            await page.locator('#approve-btn').click();await page.locator('#opening-result:not(.hidden)').wait_for(timeout=180000)
            first=await page.evaluate('state.years.at(-1)')
            assert first['extra_authorized_twd']==1700000,first['extra_authorized_twd']
            assert first['large_expense_sources']['status']=='RECONCILED'
            assert len(first['large_expense_sources']['items'])==2
            assert await page.locator('#expense-current-sources tbody tr').count()==2
            print('PHASE2_BROWSER_MULTIPLE_SCHEDULE_CPI_AND_CURRENT_SOURCES_PASS')
            # 原凍結車年重複檢查，錯誤時無部分寫入。
            before=await page.evaluate('(async()=>JSON.stringify((await request("/api/export")).payload.years))()')
            await schedule(2042,1200000,category='car',title='換車')
            assert '定期換車' in await page.locator('#alert').inner_text()
            assert await page.locator('#expense-schedule-list tbody tr').count()==3
            after=await page.evaluate('(async()=>JSON.stringify((await request("/api/export")).payload.years))()');assert before==after
            assert await page.locator('#expense-schedule-list tbody tr').first.get_by_text('已核准年度').count()==1
            # 無安全現金假冒交易；出售候選只存人工計畫，原年度資產不動。
            await page.locator('#execution-asof').fill('2036-01-15');await page.locator('#execution-fx').fill('32.50');await page.locator('#execution-fee').fill('500')
            async def holding(index,ticker,sleeve,units,price):
                row=page.locator('.execution-holding').nth(index)
                for name,value in {'ticker':ticker,'broker':'測試券商','units':str(units),'price':str(price),'lot_step':'1','quote_date':'2036-01-15'}.items():
                    await row.locator('[data-holding="'+name+'"]').fill(value)
                await row.locator('[data-holding="sleeve"]').select_option(sleeve)
            await holding(0,'STOCK','stock',6000,100);await page.locator('#execution-add-holding').click();await holding(1,'BOND','bond',3000,100)
            await page.locator('#execution-calculate').click();await page.wait_for_function('window.B85_PHASE2.getPlanning()!==null')
            planning=await page.evaluate('window.B85_PHASE2.getPlanning()');assert planning['mode']=='PLANNING_ONLY_NO_TRANSACTIONS'
            assert planning['liquidity_shortfall_twd']==0
            assert await page.evaluate('(async()=>JSON.stringify((await request("/api/export")).payload.years))()')==before
            assert '沒有下單' in await page.locator('#execution-planning-result').inner_text()
            print('PHASE2_BROWSER_SELL_CANDIDATE_UNITS_FX_AND_LEDGER_UNCHANGED_PASS')
            # 真Pyodide成對研究、取消不改資料、成功率與首次缺口定義分開。
            await page.locator('#expense-compare-run').click();await page.locator('#expense-compare-cancel').click()
            assert await page.locator('#expense-compare-status').get_attribute('data-state')=='cancelled'
            await page.locator('#expense-compare-run').click()
            await page.wait_for_function("['complete','error','cancelled'].includes(document.getElementById('expense-compare-status').dataset.state)",timeout=300000)
            assert await page.locator('#expense-compare-status').get_attribute('data-state')=='complete',await page.locator('#expense-compare-status').inner_text()
            result=await page.evaluate('window.B85_PHASE2.getComparison()');assert len(result['rows'])==4
            assert result['same_market_and_emergency_streams'];assert result['full_year_reference']
            assert all(x['diagnostics']['max_reconciliation_error_m']<1e-8 for x in result['rows'])
            assert result['rows'][1]['diagnostics']['plan_success']<result['rows'][0]['diagnostics']['plan_success']
            assert await page.locator('#expense-comparison-result tbody tr').count()==4
            async with page.expect_download() as download:await page.locator('#expense-compare-export').click()
            downloaded=await download.value;export_compare=json.loads(Path(await downloaded.path()).read_text());assert export_compare['contract']==result['contract']
            print('PHASE2_BROWSER_PAIRED_MC_FIRST_SHORTFALL_CANCEL_EXPORT_PASS',json.dumps({'seconds':[x['seconds'] for x in result['rows']],'plan':[x['diagnostics']['plan_success'] for x in result['rows']]}))
            # 修改未來排程后旧核准不动，旧研究立即失效。
            await page.locator('[data-expense-edit]').last.click();await page.locator('#expense-amount').fill('11000000');await page.locator('#expense-save').click()
            await page.wait_for_function('!document.getElementById("expense-save").disabled')
            assert await page.evaluate('window.B85_PHASE2.getComparison()===null')
            assert await page.evaluate('(async()=>JSON.stringify((await request("/api/export")).payload.years))()')==before
            # 真瀏覽器JSON.stringify數值轉型，無須reload先備份亦能還原。
            await page.locator('[data-go="history"]').first.click()
            async with page.expect_download() as download:await page.locator('#export-btn').click()
            backup=await download.value;backup_path=await backup.path();saved=json.loads(Path(backup_path).read_text())
            assert saved['sha256_contract']=='B85_NUMERIC_CANONICAL_JSON_V1';assert 'execution_plans' in saved['payload']
            backup_context=await browser.new_context(accept_downloads=True)
            restored=await backup_context.new_page();restored.on('dialog',lambda d:asyncio.create_task(d.accept()))
            await restored.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded');await restored.locator('#runtime-status.ready').wait_for(timeout=180000)
            await restored.locator('[data-go="history"]').first.click();await restored.locator('#import-file').set_input_files(backup_path)
            await restored.wait_for_function('state?.years?.length===1')
            assert await restored.evaluate('state.expense_schedule.entries.length')==3
            await restored.locator('[data-go="opening"]').first.click()
            assert await restored.locator('[data-holding="ticker"]').first.input_value()=='STOCK'
            # 第二年度以實際結算接续，只扣該年排程一次。
            await restored.locator('[data-go="closing"]').first.click();await restored.locator('#demo-close-btn').click();await restored.locator('#close-btn').click()
            await restored.locator('#closing-result:not(.hidden)').wait_for(timeout=180000)
            await restored.locator('[data-go="opening"]').first.click()
            if await restored.locator('details.cpi-manual-input').get_attribute('open') is None:
                await restored.locator('details.cpi-manual-input summary').click()
            await restored.locator('#decision_cpi').fill('132');await restored.locator('#decision_cpi_release').fill('2037-01-07')
            await restored.evaluate("document.getElementById('decision_cpi').dataset.autoSource='MANUAL'")
            await restored.locator('#approve-btn').click();await restored.wait_for_function('state.years.length===2')
            second=await restored.evaluate('state.years.at(-1)');assert second['extra_authorized_twd']==1320000
            raw=await restored.evaluate('(async()=> (await request("/api/export")).payload)()')
            assert abs(raw['years'][1]['approval']['opening']['investment_m']-raw['years'][0]['close']['investment_next_m'])<1e-8
            print('PHASE2_BROWSER_BACKUP_BEFORE_RELOAD_AND_SECOND_YEAR_ONCE_PASS')
            await restored.set_viewport_size({'width':390,'height':844});await restored.wait_for_timeout(150)
            assert await restored.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
            assert not errors,errors
            print('PHASE2_BROWSER_MOBILE_AND_ALL_CHECKS_PASS')
        except Exception:
            await page.screenshot(path='phase2-browser-failure.png',full_page=True)
            if 'restored' in locals():
                print('PHASE2_RESTORED_ALERT',await restored.locator('#alert').inner_text())
                print('PHASE2_RESTORED_FORM',await restored.locator('#opening-form').evaluate('(form)=>({valid:form.checkValidity(),invalid:[...form.querySelectorAll("input")].filter(x=>!x.checkValidity()).map(x=>({id:x.id,value:x.value,disabled:x.disabled}))})'))
            print('PHASE2_BROWSER_ERRORS',errors);print('PHASE2_ALERT',await page.locator('#alert').inner_text());raise
        finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
