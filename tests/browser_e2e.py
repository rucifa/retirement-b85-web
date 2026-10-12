"""Genuine Pyodide + NumPy + B+85 in a Chromium tab, no fake policy responses."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright,TimeoutError as PlaywrightTimeout

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=await browser.new_context(accept_downloads=True)
        page=await context.new_page()
        page.set_default_timeout(180000)
        logs=[]
        page.on('console',lambda c: logs.append('console: '+c.text[:300]))
        page.on('pageerror',lambda e: logs.append('js-error: '+str(e)[:450]))
        page.on('dialog',lambda dialog: asyncio.create_task(dialog.accept('清除演練') if dialog.type=='prompt' else dialog.accept()))
        try:
            await page.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded')
            await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            today=await page.evaluate('window.B85_TAIWAN_TIME.today()')
            previous_month=await page.evaluate('window.B85_TAIWAN_TIME.prevMonth(window.B85_TAIWAN_TIME.today())')
            assert await page.locator('#decision_date').input_value()==today
            assert await page.locator('#first_year').input_value()==today[:4]
            assert await page.locator('#start_age').input_value()=='65'
            assert await page.locator('#dashboard-baseline').is_hidden()
            assert await page.locator('#inflation-preview').is_hidden()
            assert await page.locator('#dashboard-kpis .dash-kpi').count()==4
            assert await page.locator('#dashboard-cpi-card').count()==1
            assert await page.locator('#dashboard-baseline article').count()==4
            assert await page.locator('#dashboard-lower .dash-widget').count()==4
            layout=await page.locator('.sidebar').evaluate('(el)=>getComputedStyle(el).flexDirection')
            assert layout=='row'
            assert '尚未試算' in (await page.locator('#dash-budget').inner_text())
            print('BROWSER_TAIWAN_DEFAULT_DATE_AND_AGE_65_PASS')
            print('BROWSER_DASHBOARD_NAV_AND_LAYOUT_PASS')
            print('BROWSER_PYODIDE_LOADED')
            await page.locator('#official-cpi-panel').filter(has_text='查詢基準：台灣').wait_for(timeout=120000)
            snapshot=await page.evaluate("fetch('./data/cpi_verified.json').then(x=>x.json())")
            eligible=[x for x in snapshot['records']
                      if x['publication_date']<=today and x['month']<=previous_month]
            assert eligible, 'Expected at least one published historical CPI month'
            assert previous_month in (await page.locator('#official-cpi-panel').inner_text())
            assert '尚無全年官方基準' not in (await page.locator('#official-cpi-panel').inner_text())
            # A simulation date is independent of the public as-of-Taiwan CPI snapshot.
            await page.locator('#decision_date').fill('2036-01-15')
            assert previous_month in (await page.locator('#official-cpi-panel').inner_text())
            assert await page.locator('#first_year').input_value()=='2036'
            assert await page.locator('#dashboard-baseline').is_hidden()
            await page.locator('#start_age').fill('54')
            await page.locator('.cpi-manual-input summary').click()
            await page.locator('#decision_cpi').fill('125')
            await page.locator('#decision_cpi_release').fill('2036-01-10')
            assert await page.locator('#cpi_2026').input_value()=='110'
            assert await page.locator('#inflation-preview').is_hidden()
            print('BROWSER_CPI_TAIWAN_ASOF_AND_SIMULATION_ISOLATION_PASS')
            await page.locator('#approve-btn').click()
            await page.locator('#opening-tag').filter(has_text='等待年末結算').wait_for(timeout=180000)
            a=await page.locator('#opening-result').inner_text()
            assert 'PoS' in a and '核准生活費' in a
            assert '通膨換算後正常生活費' in a
            assert '今年核准生活費' in a
            assert '738,636' in a
            assert await page.locator('#dashboard-baseline').is_visible()
            print('BROWSER_SPENDING_BASELINE_AND_INFLATION_REVEAL_ONLY_AFTER_APPROVAL_PASS')
            print('BROWSER_INFLATION_SPENDING_RESULT_PASS')
            await page.locator('#dash-budget').filter(has_text='NT$').wait_for(timeout=15000)
            assert '2036' in (await page.locator('#dash-budget-sub').inner_text())
            print('BROWSER_DASHBOARD_USES_POLICY_RESULT_PASS')
            print('BROWSER_2036_B85_APPROVAL_PASS')
            await page.locator('[data-go="closing"]').first.click()
            await page.locator('#demo-close-btn').click()
            await page.locator('#close-btn').click()
            await page.locator('#closing-result').filter(has_text='已完成年度結算').wait_for(timeout=120000)
            print('BROWSER_2036_YEAR_CLOSE_PASS')
            await page.reload(wait_until='domcontentloaded')
            await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            await page.locator('#opening-form').wait_for()
            assert '2037-01-15' == await page.locator('#decision_date').input_value()
            await page.locator('#dash-asset-chart svg').wait_for(timeout=15000)
            assert '1 年' in (await page.locator('#dash-years').inner_text())
            print('BROWSER_DASHBOARD_REAL_CLOSED_YEAR_CHART_PASS')
            print('BROWSER_LOCAL_INDEXEDDB_RESTART_PASS')
            await page.locator('[data-go="history"]').first.click()
            async with page.expect_download() as dl:
                await page.locator('#export-btn').click()
            data=json.loads(Path(await (await dl.value).path()).read_text('utf-8'))
            assert data['file_kind']=='local_yearly_research_export'
            assert len(data['payload']['years'])==1
            print('BROWSER_LOCAL_JSON_EXPORT_PASS')
            await page.locator('#import-file').set_input_files({'name':'B85_年度研究備份.json','mimeType':'application/json','buffer':json.dumps(data,ensure_ascii=False).encode('utf-8')})
            await page.locator('#alert').filter(has_text='匯入完成').wait_for(timeout=120000)
            print('BROWSER_LOCAL_JSON_IMPORT_PASS')
            assert '2036' in (await page.locator('#history-list').inner_text())
            print('B85_PAGES_BROWSER_PYODIDE_E2E_PASS')
            await page.route('**/data/cpi_verified.json',lambda route:route.abort())
            await page.reload(wait_until='domcontentloaded')
            await page.locator('#official-cpi-panel[data-status="error"]').wait_for(timeout=15000)
            assert '保留原手動輸入' in (await page.locator('#official-cpi-panel').inner_text())
            await page.unroute('**/data/cpi_verified.json')
            async def bad_json(route):
                await route.fulfill(status=200,content_type='application/json',body='{}')
            await page.route('**/data/cpi_verified.json',bad_json)
            await page.reload(wait_until='domcontentloaded')
            await page.locator('#official-cpi-panel[data-status="error"]').wait_for(timeout=15000)
            print('BROWSER_CPI_OFFLINE_AND_INVALID_SCHEMA_PASS')
        except Exception:
            print('BROWSER_FAILURE_LAST_LOGS',json.dumps(logs[-15:],ensure_ascii=False))
            try: await page.screenshot(path='/tmp/b85_pages_browser_failure.png',full_page=True,timeout=2000)
            except Exception:pass
            raise
        finally:
            await browser.close()

if __name__=='__main__':asyncio.run(main())
