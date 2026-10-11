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
            print('BROWSER_PYODIDE_LOADED')
            await page.locator('#approve-btn').click()
            await page.locator('#opening-tag').filter(has_text='等待年末結算').wait_for(timeout=180000)
            a=await page.locator('#opening-result').inner_text()
            assert 'PoS' in a and '核准生活費' in a
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
        except Exception:
            print('BROWSER_FAILURE_LAST_LOGS',json.dumps(logs[-15:],ensure_ascii=False))
            try: await page.screenshot(path='/tmp/b85_pages_browser_failure.png',full_page=True,timeout=2000)
            except Exception:pass
            raise
        finally:
            await browser.close()

if __name__=='__main__':asyncio.run(main())
