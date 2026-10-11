"""Offline CPI public-pipeline tests: no network, no private data, no secrets."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

THIS=Path(__file__).resolve()
ROOT=THIS.parents[3]
sys.path.insert(0,str(THIS.parents[1]))

import update
import cpi_sources as src

NOW=datetime(2026,10,12,8,tzinfo=timezone.utc)
SHA='a'*64
NEWS='https://www.stat.gov.tw/News_Content.aspx?n=2668&s=236540'
def official(month,idx,yoy,release,status,primary=None):
    row={'month':month,'index_2021_100':str(idx),'bulletin_yoy':str(yoy),
         'table1_yoy':str(yoy),'release_date':release,'result':status,
         'url':NEWS,'xlsx_sha256':SHA,'html_sha256':SHA}
    if primary is not None:row['primary_index_2021_100']=str(primary)
    return row

def prev():
    return {
       'schema_version':1,'source_authority':'行政院主計總處（DGBAS）',
       'index_base':'2021=100','annual_2026_index':None,'annual_2026_release_date':None,
       'latest_cross_verified_month':'2026-07',
       'records':[
         {'month':'2026-07','index':112.35,'official_yoy_pct':2.54,
          'publication_date':'2026-08-06','verification':'CROSS_VERIFIED',
          'official_source_url':NEWS,'primary_index':112.35,'bulletin_xlsx_sha256':SHA}
       ]
    }

def assessment(*records):
    verified=sorted(r['month'] for r in records if r['result']=='CROSS_VERIFIED')
    pending=sorted(r['month'] for r in records if r['result']=='BULLETIN_ONLY_PENDING_PRIMARY')
    return {'status':'BULLETIN_AHEAD_PENDING_PRIMARY' if pending else 'CROSS_VERIFIED',
            'records':list(records),'secondary_latest':max(r['month'] for r in records),
            'verified_months':verified,'pending_months':pending,'conflicting_months':[]}

class PublicCpiTests(unittest.TestCase):
    def test_existing_public_official_fixture_matches_schema(self):
        current=__import__('json').loads((ROOT/'data/cpi_verified.json').read_text('utf-8'))
        history=update.valid_old(current,NOW.date())
        self.assertEqual(current['latest_cross_verified_month'],'2026-07')
        self.assertEqual(len(history),4)
        self.assertEqual(history['2026-09']['verification'],'BULLETIN_ONLY_PENDING_PRIMARY')
        self.assertEqual(history['2026-06']['verification'],'HISTORICAL_VINTAGE_DIFFERENCE')

    def test_last_four_bulletins_merge_and_pending_is_not_verified(self):
        rows=[
          official('2026-07',112.35,2.54,'2026-08-06','CROSS_VERIFIED',112.35),
          official('2026-08',112.32,2.04,'2026-09-08','BULLETIN_ONLY_PENDING_PRIMARY'),
          official('2026-09',112.82,2.73,'2026-10-07','BULLETIN_ONLY_PENDING_PRIMARY')
        ]
        snap=update.build_snapshot({'2026-07':'112.35'},assessment(*rows),SHA,SHA,prev(),NOW)
        self.assertEqual(snap['latest_cross_verified_month'],'2026-07')
        self.assertEqual(snap['records'][-1]['verification'],'BULLETIN_ONLY_PENDING_PRIMARY')
        self.assertIsNone(snap['annual_2026_index'])
        self.assertNotIn('research_only',snap)

    def test_upgrade_pending_only_if_primary_equal(self):
        old=prev()
        pending=official('2026-08',112.32,2.04,'2026-09-08','CROSS_VERIFIED',112.32)
        result=update.build_snapshot(
            {'2026-07':'112.35','2026-08':'112.32'},
            assessment(pending),SHA,SHA,old,NOW)
        self.assertEqual(result['latest_cross_verified_month'],'2026-08')
        self.assertEqual(result['records'][-1]['verification'],'CROSS_VERIFIED')

    def test_unverified_new_primary_rejected(self):
        with self.assertRaisesRegex(update.PublishError,'NEW_PRIMARY_MONTH_UNVERIFIED'):
            update.build_snapshot(
                {'2026-07':'112.35','2026-08':'112.32'},
                assessment(official('2026-08',112.32,2.04,'2026-09-08','BULLETIN_ONLY_PENDING_PRIMARY')),
                SHA,SHA,prev(),NOW)

    def test_old_verified_downgrade_rejected(self):
        with self.assertRaisesRegex(update.PublishError,'HISTORICALLY_VERIFIED'):
            update.build_snapshot(
                {'2026-07':'112.35'},
                assessment(official('2026-07',112.35,2.54,'2026-08-06','BULLETIN_ONLY_PENDING_PRIMARY')),
                SHA,SHA,prev(),NOW)

    def test_old_verified_change_rejected(self):
        with self.assertRaisesRegex(update.PublishError,'HISTORICALLY_VERIFIED'):
            update.build_snapshot(
                {'2026-07':'112.35'},
                assessment(official('2026-07',113.15,2.54,'2026-08-06','CROSS_VERIFIED',113.15)),
                SHA,SHA,prev(),NOW)

    def test_invalid_official_url_rejected(self):
        bad=official('2026-09',112.82,2.73,'2026-10-07','BULLETIN_ONLY_PENDING_PRIMARY')
        bad['url']='https://untrusted.example.com'
        with self.assertRaisesRegex(update.PublishError,'UNTRUSTED'):
            update.public_record(bad,NOW.date())

    def test_future_announcement_rejected(self):
        bad=official('2026-09',112.82,2.73,'2026-10-18','BULLETIN_ONLY_PENDING_PRIMARY')
        with self.assertRaisesRegex(update.PublishError,'FUTURE'):
            update.public_record(bad,NOW.date())

    def test_false_verification_rejected(self):
        bad=official('2026-08',112.32,2.04,'2026-09-08','CROSS_VERIFIED',112.99)
        with self.assertRaisesRegex(update.PublishError,'INVALID_PRIMARY'):
            update.public_record(bad,NOW.date())

    def test_primary_baseline_absent_is_blocking(self):
        with self.assertRaisesRegex(update.PublishError,'BASELINE_INCOMPLETE'):
            update.check_primary_history({'2026-07':'112.35'})

    def test_unsafe_tls_host_fails_without_request(self):
        with self.assertRaisesRegex(src.DualSourceError,'Unapproved'):
            src.https_bytes('https://evil.example/sheet.xlsx',None,'ws.dgbas.gov.tw',1000)

    def test_statistical_mean_does_not_become_annual_baseline(self):
        sample=official('2026-07',112.35,2.54,'2026-08-06','CROSS_VERIFIED',112.35)
        result=update.build_snapshot({'2026-07':'112.35'},assessment(sample),SHA,SHA,prev(),NOW)
        self.assertIsNone(result['annual_2026_index'])
        self.assertIsNone(result['annual_2026_release_date'])

if __name__=='__main__':
    unittest.main()
