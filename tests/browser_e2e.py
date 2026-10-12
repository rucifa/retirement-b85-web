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
        async def handle_dialog(dialog):
            if '清除這個瀏覽器' in dialog.message:
                assert chr(92)+'n' not in dialog.message
                assert chr(10) in dialog.message
            await dialog.accept('清除演練') if dialog.type=='prompt' else await dialog.accept()
        page.on('dialog',lambda dialog: asyncio.create_task(handle_dialog(dialog)))
        try:
            await page.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded')
            await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            assert await page.locator('.runtime-stage').count()==3
            assert await page.locator('#runtime-stage-engine-pct').inner_text()=='100%'
            assert await page.locator('#runtime-stage-storage-pct').inner_text()=='100%'
            await page.locator('#runtime-stage-cpi[data-state="ready"]').wait_for(timeout=15000)
            assert await page.locator('#runtime-stage-cpi-pct').inner_text()=='100%'
            assert await page.locator('#runtime-total-bar').get_attribute('style')=='width: 100%;'
            assert await page.locator('#dashboard-baseline').count()==0
            form_bounds=await page.locator('#opening-form').bounding_box()
            assert form_bounds is not None
            async def box(selector):
                bounds=await page.locator(selector).bounding_box()
                assert bounds is not None, selector
                return bounds
            cpi=await box('#dashboard-cpi-card')
            policy=await box('#dashboard-rail .dash-policy-card')
            assets=await box('#dashboard-lower .dash-history-chart')
            years=await box('#dashboard-lower .dash-history-summary')
            notes=await box('#dashboard-lower .dash-risk-notes')
            # Two-column desktop: no giant full-width CPI chart or misplaced blank column.
            assert abs(cpi['x']-form_bounds['x'])<4
            assert abs(cpi['y']-policy['y'])<4
            assert policy['x']>=cpi['x']+cpi['width']-4
            assert abs(cpi['width']+policy['width']+(policy['x']-cpi['x']-cpi['width'])-form_bounds['width'])<5
            assert abs(assets['x']-form_bounds['x'])<4
            assert abs(assets['y']-years['y'])<4
            assert years['x']>=assets['x']+assets['width']-4
            assert abs(notes['x']-years['x'])<4
            assert notes['y']>=years['y']+years['height']-3
            await page.locator('#dash-cpi-trend svg').wait_for(timeout=15000)
            plot=await box('#dash-cpi-trend svg')
            assert plot['height']<270 and plot['width']<=cpi['width']-15, (plot,cpi)
            # Below 1120px the modules switch to one column, never horizontal overflow.
            await page.set_viewport_size({'width':1000,'height':900})
            await page.wait_for_timeout(200)
            compact_cpi=await box('#dashboard-cpi-card')
            compact_policy=await box('#dashboard-rail .dash-policy-card')
            compact_assets=await box('#dashboard-lower .dash-history-chart')
            compact_years=await box('#dashboard-lower .dash-history-summary')
            compact_notes=await box('#dashboard-lower .dash-risk-notes')
            assert abs(compact_cpi['x']-compact_policy['x'])<3
            assert compact_policy['y']>=compact_cpi['y']+compact_cpi['height']-3
            assert abs(compact_assets['x']-compact_years['x'])<3
            assert compact_years['y']>=compact_assets['y']+compact_assets['height']-3
            assert compact_notes['y']>=compact_years['y']+compact_years['height']-3
            await page.set_viewport_size({'width':1280,'height':720})
            print('BROWSER_RESPONSIVE_BALANCED_DASHBOARD_AND_THREE_STAGE_RUNTIME_PASS')
            today=await page.evaluate('window.B85_TAIWAN_TIME.today()')
            previous_month=await page.evaluate('window.B85_TAIWAN_TIME.prevMonth(window.B85_TAIWAN_TIME.today())')
            assert await page.locator('#decision_date').input_value()==today
            assert await page.locator('#first_year').input_value()==today[:4]
            assert await page.locator('#start_age').input_value()=='65'
            assert await page.evaluate("window.B85_TAIWAN_TIME.prevMonth('2027-01-01')")=='2026-12'
            assert await page.evaluate("window.B85_TAIWAN_TIME.prevMonth('2026-03-31')")=='2026-02'
            assert await page.locator('#use-january-date').is_hidden()
            assert '首次退休可選任何日期' in (await page.locator('#decision-month-guidance').inner_text())

            assert await page.locator('#inflation-preview').is_hidden()
            assert await page.locator('#dashboard-kpis .dash-kpi').count()==4
            assert await page.locator('#dashboard-kpis #dash-cpi-month, #dashboard-kpis #dash-years').count()==0
            assert await page.locator('#dashboard-cpi-card').count()==1
            assert await page.locator('#dashboard-baseline').count()==0
            assert await page.locator('#dashboard-lower .dash-widget').count()==3
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
            latest_public=eligible[-1]
            latest_rate=('+' if latest_public['official_yoy_pct']>0 else '')+f"{latest_public['official_yoy_pct']:.2f}%"
            await page.locator('#official-cpi-panel').filter(has_text='最新月份年增率').wait_for(timeout=15000)
            panel=await page.locator('#official-cpi-panel').inner_text()
            assert latest_rate in panel
            assert latest_public['month'] in panel
            assert await page.locator('#latest-cpi-index').inner_text()==f"{latest_public['index']:.2f}"
            cpi_months=[x for x in snapshot['current_year_chart']
                if x['month'].startswith('2026-') and x['month']<=latest_public['month']]
            annual_proxy=sum(x['index'] for x in cpi_months)/len(cpi_months)
            assert abs(float(await page.locator('#cpi_2026').input_value())-annual_proxy)<0.011
            assert '1～' in (await page.locator('#cpi-reference-explanation').inner_text())
            assert await page.locator('#floor_spend_2026_twd').input_value()==''
            assert await page.locator('#normal_spend_2026_twd').input_value()==''
            assert not await page.locator('#core_spend_2026_twd').is_visible()
            print('BROWSER_NO_FIXED_110_CPI_AND_MINIMUM_FIRST_SPENDING_PASS')
            assert await page.locator('.cpi-manual-input').is_visible()
            chart=snapshot.get('current_year_chart') or []
            assert len(chart)<=12
            if snapshot.get('latest_official_ytd'):
                assert '平均較去年同期' in panel
                assert chart and chart[0]['month'].endswith('-01')
                assert chart[-1]['month']==latest_public['month']
                expected_ytd=snapshot['latest_official_ytd']['average_yoy_pct']
                assert f"{expected_ytd:+.2f}%" in panel
                await page.locator('#dash-cpi-trend svg').wait_for(timeout=15000)
                hits=page.locator('#dash-cpi-trend .cpi-point-hit')
                assert await hits.count()==len(chart)
                await hits.first.hover()
                tooltip=page.locator('#dash-cpi-trend .cpi-hover-tooltip')
                await tooltip.wait_for(state='visible',timeout=5000)
                assert chart[0]['month'].replace('-',' 年 ') in (await tooltip.inner_text())
                first_rate=chart[0]['yoy_pct']
                assert f"{first_rate:+.2f}%" in (await tooltip.inner_text())
                assert ('歷史指數計算值' if chart[0]['origin']=='OFFICIAL_HISTORICAL_INDEX_DERIVED' else '官方公告') in (await tooltip.inner_text())
                await hits.last.focus()
                assert chart[-1]['month'].replace('-',' 年 ') in (await tooltip.inner_text())
                print('BROWSER_CPI_POINT_HOVER_KEYBOARD_RATE_AND_PROVENANCE_PASS')
                print('BROWSER_OFFICIAL_YTD_AND_JAN_TO_DATE_CHART_PASS')
            assert '上個月官方資料狀態' not in panel
            await page.locator('#dash-cpi-month').filter(has_text=latest_public['month'].replace('-',' / ')).wait_for(timeout=15000)
            assert latest_rate in (await page.locator('#dash-cpi-sub').inner_text())
            print('BROWSER_GITHUB_LATEST_PUBLISHED_OFFICIAL_YOY_PASS')
            assert previous_month in (await page.locator('#official-cpi-panel').inner_text())
            assert '尚無全年官方基準' not in (await page.locator('#official-cpi-panel').inner_text())
            # A simulation date is independent of the public as-of-Taiwan CPI snapshot.
            await page.locator('#decision_date').fill('2036-10-12')
            assert previous_month in (await page.locator('#official-cpi-panel').inner_text())
            assert await page.locator('#first_year').input_value()=='2036'
            await page.locator('#start_age').fill('54')
            await page.locator('.cpi-manual-input summary').click()
            await page.locator('#decision_cpi').fill('125')
            await page.locator('#decision_cpi_release').fill('2036-10-07')
            assert abs(float(await page.locator('#cpi_2026').input_value())-annual_proxy)<0.011
            await page.locator('#floor_spend_2026_twd').fill('500000')
            assert '最低需求' in (await page.locator('#spending-profile-preview').inner_text())
            await page.locator('#normal_spend_2026_twd').fill('650000')
            assert await page.locator('#core_spend_2026_twd').input_value()=='600000'
            assert await page.locator('#inflation-preview').is_hidden()
            print('BROWSER_CPI_TAIWAN_ASOF_AND_SIMULATION_ISOLATION_PASS')
            await page.locator('#approve-btn').click()
            await page.locator('#opening-tag').filter(has_text='等待年末結算').wait_for(timeout=180000)
            a=await page.locator('#opening-result').inner_text()
            assert 'PoS' in a and '建議生活費' in a
            assert '通膨換算後正常生活費' in a
            assert '今年建議生活費' in a
            # A single primary annual result; no second large recommendation widget.
            assert await page.locator('#opening-result .metric.featured').count()==1
            assert await page.locator('.dash-recommendation, #dash-recommend-body').count()==0
            assert await page.locator('.dash-history-summary').count()==1
            assert await page.locator('.dash-risk-notes').count()==1
            assert await page.locator('#dash-budget').inner_text()!='尚未試算'
            import re
            converted=650000*125/float(await page.locator('#cpi_2026').input_value())
            match=re.search(r'通膨換算後正常生活費\s+NT\$\s*([\d,]+)',a)
            assert match is not None, a
            assert abs(float(match.group(1).replace(',',''))-converted)<2
            assert '81/366' in a
            assert '全年模型參考 PoS' in a
            assert '首年' in (await page.locator('#dash-budget-sub').inner_text())
            # Year-one floor/recommendation difference uses the SAME CPI-adjusted
            # nominal year and the same 81/366-day spending period as the engine.
            model_year=await page.evaluate('() => state.years[state.years.length-1]')
            comparable=await page.evaluate('y => window.B85_BUDGET_COMPARISON.compare(y)',model_year)
            assert comparable['minimum']==round(model_year['floor_reference_twd']*model_year['calendar_fraction'])
            assert comparable['recommended']==round(model_year['living_authorized_twd'])
            assert await page.locator('#dash-minimum').inner_text()==f"NT$ {comparable['minimum']:,}"
            if comparable['difference']>0:
                assert await page.locator('#dash-difference-card').get_attribute('data-state')=='surplus'
                assert await page.locator('#dash-difference').inner_text()==f"＋NT$ {comparable['difference']:,}"
            elif comparable['difference']<0:
                assert await page.locator('#dash-difference-card').get_attribute('data-state')=='shortfall'
                assert await page.locator('#dash-difference').inner_text()==f"−NT$ {abs(comparable['difference']):,}"
            else:
                assert await page.locator('#dash-difference-card').get_attribute('data-state')=='equal'
            # Deterministic independent UI cases: positive, negative, invalid and full year.
            cases=await page.evaluate('''() => {
              const calc=window.B85_BUDGET_COMPARISON.compare;
              return [
                calc({floor_reference_twd:400000,living_authorized_twd:593034,calendar_first_year:true,calendar_fraction:317/365}),
                calc({floor_reference_twd:400000,living_authorized_twd:310000,calendar_first_year:true,calendar_fraction:1}),
                calc({floor_reference_twd:400000,living_authorized_twd:410000,calendar_first_year:false,calendar_fraction:0.5}),
                calc({floor_reference_twd:400000,living_authorized_twd:410000,calendar_first_year:true,calendar_fraction:0}),
                calc({floor_reference_twd:null,living_authorized_twd:410000})
              ];
            }''')
            assert cases[0]['minimum']==round(400000*317/365) and cases[0]['difference']>0
            assert cases[1]['difference']<0
            assert cases[2]['minimum']==400000 and cases[2]['difference']==10000
            assert cases[3] is None and cases[4] is None
            print('BROWSER_LIVING_FLOOR_SAME_PERIOD_CPI_AND_SHORTFALL_CASES_PASS')
            assert await page.locator('#dash-guardrail-pos').inner_text()!='—'
            assert await page.locator('[data-guardrail-zone].active').count()==1
            assert 'Guardrail 後全年額度' in (await page.locator('#dash-guardrail-breakdown').inner_text())
            assert '正常生活費參考' in (await page.locator('#dash-guardrail-breakdown').inner_text())
            await page.locator('#dash-scenario-chart svg').wait_for(timeout=15000)
            assert await page.locator('#dash-scenario-pane').is_visible()
            assert await page.locator('#dash-actual-tab').get_attribute('aria-pressed')=='false'
            assert await page.locator('#dash-scenario-tab').get_attribute('aria-pressed')=='true'
            await page.locator('#dash-return-low').fill('-3')
            assert await page.locator('#dash-scenario-chart svg path').count()==3
            assert '假設值' in (await page.locator('.dash-scenario-disclaimer').inner_text())
            await page.locator('#dash-actual-tab').click()
            assert await page.locator('#dash-asset-chart').is_visible()
            await page.locator('#dash-scenario-tab').click()
            print('BROWSER_GUARDRAIL_REAL_POLICY_AND_USER_EDITABLE_SCENARIOS_PASS')
            print('BROWSER_OCTOBER_FIRST_YEAR_ACTUAL_DAY_PRORATION_PASS')
            assert await page.locator('#dashboard-baseline').count()==0
            print('BROWSER_SPENDING_BASELINE_REMOVED_TO_AVOID_DUPLICATION_PASS')
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
            assert await page.locator('#decision_cpi_release').input_value()!='2037-01-10', 'Fabricated future CPI publication date'
            print('BROWSER_CPI_NEXT_YEAR_NO_FABRICATED_RELEASE_DATE_PASS')
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
            saved_manual_cpi=await page.locator('#decision_cpi').input_value()
            await page.route('**/data/cpi_verified.json',lambda route:route.abort())
            await page.reload(wait_until='domcontentloaded')
            await page.locator('#official-cpi-panel[data-status="error"]').wait_for(timeout=15000)
            await page.locator('#runtime-stage-cpi[data-state="failed"]').wait_for(timeout=15000)
            assert await page.locator('#runtime-stage-cpi-pct').inner_text()=='0%'
            # CPI fetch fails before the worker restores IndexedDB. Wait for both.
            await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            assert '1 年' in (await page.locator('#dash-years').inner_text())
            assert await page.locator('#decision_cpi').input_value()==saved_manual_cpi
            assert '1 年' in (await page.locator('#dash-years').inner_text())
            print('BROWSER_CPI_OFFLINE_PRESERVES_MANUAL_INPUT_AND_HISTORY_PASS')
            await page.unroute('**/data/cpi_verified.json')
            async def bad_json(route):
                await route.fulfill(status=200,content_type='application/json',body='{}')
            await page.route('**/data/cpi_verified.json',bad_json)
            await page.reload(wait_until='domcontentloaded')
            await page.locator('#official-cpi-panel[data-status="error"]').wait_for(timeout=15000)
            await page.locator('#runtime-stage-cpi[data-state="failed"]').wait_for(timeout=15000)
            assert await page.locator('#runtime-stage-cpi-pct').inner_text()=='0%'
            # CPI fetch fails before the worker restores IndexedDB. Wait for both.
            await page.locator('#runtime-status.ready').wait_for(timeout=180000)
            assert '1 年' in (await page.locator('#dash-years').inner_text())
            assert await page.locator('#decision_cpi').input_value()==saved_manual_cpi
            print('BROWSER_CPI_OFFLINE_AND_INVALID_SCHEMA_PASS')
            await page.locator('[data-go="history"]').first.click()
            async with page.expect_download() as backup:
                await page.locator('#reset-btn').click()
            downloaded=json.loads(Path(await (await backup.value).path()).read_text('utf-8'))
            assert downloaded['payload']['years'] and downloaded['file_kind']=='local_yearly_research_export'
            await page.locator('#dash-years').filter(has_text='0 年').wait_for(timeout=180000)
            assert '還沒有年度紀錄' in (await page.locator('#history-list').inner_text())
            print('BROWSER_RESET_BY_CONFIRM_BUTTON_AND_AUTO_JSON_BACKUP_PASS')
            # Fresh, separate IndexedDB state: Jan 1, 2026 has no historical
            # published record in the current public JSON; use explicitly
            # labeled 2026 baseline scenario, not a fabricated official index.
            context_jan=await browser.new_context()
            jan=await context_jan.new_page()
            try:
                await jan.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded')
                await jan.locator('#runtime-status.ready').wait_for(timeout=180000)
                await jan.locator('#decision_date').fill('2026-01-01')
                await jan.locator('#decision_cpi').evaluate("(el)=>{el.blur()}")
                await jan.locator('#cpi-decision-asof-note').filter(has_text='演練假設').wait_for(timeout=15000)
                assert abs(float(await jan.locator('#decision_cpi').input_value())-annual_proxy)<0.011
                assert await jan.locator('#decision_cpi_release').input_value()=='2026-01-01'
                assert await jan.locator('#decision-cpi-date-caption').text_content()=='演練假設生效日（非官方公布日）'
                assert await jan.locator('#decision_cpi').get_attribute('data-auto-source')=='SCENARIO_2026_BASELINE'
                await jan.locator('#floor_spend_2026_twd').fill('500000')
                await jan.locator('#normal_spend_2026_twd').fill('650000')
                await jan.locator('#approve-btn').click()
                await jan.locator('#opening-tag').filter(has_text='等待年末結算').wait_for(timeout=180000)
                assert '本年 CPI 為演練假設' in (await jan.locator('#opening-result').inner_text())
                print('BROWSER_JANUARY_FIRST_NO_OFFICIAL_CPI_SCENARIO_APPROVED_PASS')
            finally:
                await context_jan.close()
            # Independent new user: personalized 2026-real spending must
            # flow through the real browser worker into the saved plan and UI.
            context_custom=await browser.new_context()
            custom=await context_custom.new_page()
            try:
                await custom.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded')
                await custom.locator('#runtime-status.ready').wait_for(timeout=180000)
                await custom.locator('#decision_date').fill('2026-01-01')
                await custom.locator('#cpi-decision-asof-note').filter(has_text='演練假設').wait_for(timeout=15000)
                await custom.locator('#floor_spend_2026_twd').fill('520000')
                await custom.locator('#normal_spend_2026_twd').fill('920000')
                assert await custom.locator('#core_spend_2026_twd').input_value()=='786667'
                await custom.locator('#spending-core-details summary').click()
                await custom.locator('#core_spend_2026_twd').fill('700000')
                assert await custom.locator('#spending-profile-preview').get_attribute('data-valid')=='true'
                await custom.locator('#approve-btn').click()
                await custom.locator('#opening-tag').filter(has_text='等待年末結算').wait_for(timeout=180000)
                assert '個人化生活費研究 v1' in (await custom.locator('#dash-engine-name').inner_text())
                assert '920,000' in (await custom.locator('#dash-guardrail-breakdown').inner_text())
                saved_profile=await custom.evaluate('() => state.plan.spending_profile')
                assert saved_profile['normal_twd']==920000
                assert saved_profile['core_twd']==700000
                assert saved_profile['floor_twd']==520000
                print('BROWSER_PERSONALIZED_SPENDING_MODEL_AND_DYNAMIC_BASELINE_PASS')
            finally:
                await context_custom.close()
            # Someone who only knows their minimum essential expenses must
            # still be able to complete a real annual approval.
            context_basic=await browser.new_context()
            essential=await context_basic.new_page()
            try:
                await essential.goto('http://127.0.0.1:8766/',wait_until='domcontentloaded')
                await essential.locator('#runtime-status.ready').wait_for(timeout=180000)
                await essential.locator('#decision_date').fill('2026-01-01')
                await essential.locator('#cpi-decision-asof-note').filter(has_text='演練假設').wait_for(timeout=15000)
                await essential.locator('#floor_spend_2026_twd').fill('350000')
                assert await essential.locator('#normal_spend_2026_twd').input_value()==''
                assert await essential.locator('#core_spend_2026_twd').input_value()=='350000'
                assert '最低需求' in (await essential.locator('#spending-profile-preview').inner_text())
                await essential.locator('#approve-btn').click()
                await essential.locator('#opening-tag').filter(has_text='等待年末結算').wait_for(timeout=180000)
                saved=await essential.evaluate('() => state.plan.spending_profile')
                assert saved['normal_twd']==350000
                assert saved['core_twd']==350000
                assert saved['floor_twd']==350000
                assert '今年建議生活費' in (await essential.locator('#opening-result').inner_text())
                await essential.locator('.capacity-research .capacity-grid article').first.wait_for(timeout=180000)
                inverse_text=await essential.locator('.capacity-research').inner_text()
                assert '95%' in inverse_text and '99%' in inverse_text
                assert '不是經完整動態驗證的最高安全提領額' in inverse_text
                read_only=await essential.evaluate('() => state.years.length')
                assert read_only==1
                print('BROWSER_INVERSE_CAPACITY_RESEARCH_ONLY_AND_DUAL_THRESHOLD_PASS')
                print('BROWSER_MINIMUM_ONLY_OPTIONAL_DESIRED_SPENDING_PASS')
            finally:
                await context_basic.close()
        except Exception:
            print('BROWSER_FAILURE_LAST_LOGS',json.dumps(logs[-15:],ensure_ascii=False))
            try: await page.screenshot(path='/tmp/b85_pages_browser_failure.png',full_page=True,timeout=2000)
            except Exception:pass
            raise
        finally:
            await browser.close()

if __name__=='__main__':asyncio.run(main())
