import json
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'output'))
import index_crosscheck as ic


class CrosscheckTests(unittest.TestCase):
    def run_case(self, em_close='100', em_day='2026-10-20', missing=False, now=None):
        def fetch(url, **kwargs):
            if 'yahoo' in url:
                stamp = int(datetime(2026, 10, 20, 8, tzinfo=timezone.utc).timestamp())
                return {'chart': {'result': [{'timestamp': [stamp], 'indicators': {'quote': [{'close': [100]}]}}]}}
            if missing:
                return None
            return {'data': {'name': '恒生指数', 'klines': [f'{em_day},100,{em_close},101,99,1']}}
        with patch.object(ic, 'SPECS', ic.SPECS[:1]):
            return ic.collect(fetch, now=now or datetime(2026, 10, 21, tzinfo=timezone.utc))[0]

    def test_agreement(self):
        r = self.run_case()
        self.assertTrue(r['usable'])
        self.assertIsNone(r['ret_20d'])

    def test_conflict(self):
        self.assertEqual(self.run_case(em_close='102')['status'], '来源冲突')

    def test_misaligned(self):
        self.assertEqual(self.run_case(em_day='2026-10-19')['status'], '交易日错位')

    def test_missing(self):
        self.assertEqual(self.run_case(missing=True)['status'], '单源待核验')

    def test_stale(self):
        self.assertEqual(self.run_case(now=datetime(2026, 10, 27, tzinfo=timezone.utc))['status'], '数据过期')

    def test_invalid_close(self):
        for close in ['nan', 'inf', '-1', '0']:
            self.assertFalse(self.run_case(em_close=close)['usable'])

    def test_intraday_filtered(self):
        self.assertEqual(ic._clean([('2026-10-21', 100)], '^HSI', datetime(2026, 10, 21, 3, tzinfo=timezone.utc)), {})

    def test_ixic_accepts_eastmoney_nasdaq_composite_and_blocks_100(self):
        ixic_spec = [s for s in ic.SPECS if s[2] == '^IXIC']
        stamp = int(datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc).timestamp())
        now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)

        def fetch_ok(url, **kwargs):
            if 'yahoo' in url:
                return {'chart': {'result': [{'timestamp': [stamp], 'indicators': {'quote': [{'close': [26702.86]}]}}]}}
            if 'push2his' in url:
                return {'data': {'name': '纳斯达克', 'klines': ['2026-10-21,26500,26702.86,26800,26400,100']}}
            return None

        def fetch_ndx100(url, **kwargs):
            if 'yahoo' in url:
                return {'chart': {'result': [{'timestamp': [stamp], 'indicators': {'quote': [{'close': [26702.86]}]}}]}}
            if 'push2his' in url:
                return {'data': {'name': '纳斯达克100', 'klines': ['2026-10-21,26500,26702.86,26800,26400,100']}}
            return None

        with patch.object(ic, 'SPECS', ixic_spec):
            ok_row = ic.collect(fetch_ok, now=now)[0]
            bad_row = ic.collect(fetch_ndx100, now=now)[0]
        self.assertTrue(ok_row['usable'])
        self.assertEqual(ok_row['status'], '双源一致')
        self.assertFalse(bad_row['usable'])
        self.assertEqual(bad_row['status'], '单源待核验')

    def test_eastmoney_mirror_and_hstech_multi_peer_failover(self):
        from datetime import date, timedelta
        hstech_spec = [s for s in ic.SPECS if s[2] == '^HSTECH']
        now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
        start = date(2026, 6, 15)
        tx_days = []
        for i in range(95):
            d = start + timedelta(days=i)
            tx_days.append([d.isoformat(), '3500', str(3500 + i), '3900', '3400', '100'])
        tx_days.append(['2026-10-22', '3800', '3793.93', '3850', '3750', '100'])

        def fetch(url, params=None, **kwargs):
            # Yahoo ^HSTECH 404，HSTECH.HK 历史日K + meta 当天收盘；东财主站断连、100.HSTECH 无数据，走腾讯日K
            if 'HSTECH.HK' in url:
                close_ts = int(datetime(2026, 10, 22, 8, 9, tzinfo=timezone.utc).timestamp())
                ts = [int(datetime(int(r[0][:4]), int(r[0][5:7]), int(r[0][8:10]), 8, 9, tzinfo=timezone.utc).timestamp())
                      for r in tx_days[:-1]]
                closes = [float(r[2]) for r in tx_days[:-1]]
                return {'chart': {'result': [{'meta': {'regularMarketPrice': 3793.93, 'regularMarketTime': close_ts},
                                              'timestamp': ts, 'indicators': {'quote': [{'close': closes}]}}]}}
            if 'ifzq.gtimg.cn' in url:
                return {'data': {'hkHSTECH': {'day': tx_days}}}
            return None

        with patch.object(ic, 'SPECS', hstech_spec):
            r = ic.collect(fetch, now=now)[0]
        self.assertTrue(r['usable'])
        self.assertEqual(r['status'], '双源一致')
        self.assertEqual(r['as_of'], '2026-10-22')
        self.assertIsNotNone(r['ret_20d'])
        self.assertIsNotNone(r['ma60'])

    def test_yahoo_post_midnight_meta_recovers_just_closed_session(self):
        spec = [s for s in ic.SPECS if s[2] == '^HSI']
        # 模拟凌晨 01:51 CST：timestamp 仅到 10-20，meta 已是 10-21 16:09 HKT 收盘
        t_prev = int(datetime(2026, 10, 20, 8, 10, tzinfo=timezone.utc).timestamp())
        t_curr = int(datetime(2026, 10, 21, 8, 9, tzinfo=timezone.utc).timestamp())
        now = datetime(2026, 10, 21, 17, 51, tzinfo=timezone.utc)

        def fetch(url, **kwargs):
            if 'yahoo' in url:
                return {'chart': {'result': [{
                    'meta': {'regularMarketPrice': 23651.87, 'regularMarketTime': t_curr},
                    'timestamp': [t_prev],
                    'indicators': {'quote': [{'close': [23867.74]}]},
                }]}}
            return {'data': {'name': '恒生指数', 'klines': ['2026-10-21,23800,23651.87,23900,23500,1']}}

        with patch.object(ic, 'SPECS', spec):
            r = ic.collect(fetch, now=now)[0]
        self.assertTrue(r['usable'])
        self.assertEqual(r['as_of'], '2026-10-21')

    def test_market_db_fallback_never_contaminates_overseas_leg(self):
        spec = [s for s in ic.SPECS if s[2] == '^HSI']
        now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
        close_ts = int(datetime(2026, 10, 22, 8, 9, tzinfo=timezone.utc).timestamp())
        yahoo_only_doc = {
            'slots': {
                '1700': {
                    'quotes': {
                        '^HSI': {
                            'consensus': {
                                'by_source': {'yahoo': {'price': 22934.68, 'quote_time': '2026-10-22 16:08:58'}},
                            }
                        }
                    }
                }
            }
        }
        dom_doc = {
            'slots': {
                '1700': {
                    'quotes': {
                        '^HSI': {
                            'consensus': {
                                'by_source': {'sina': {'price': 22934.68, 'quote_time': '2026-10-22 16:08:58'}},
                            }
                        }
                    }
                }
            }
        }
        live_overseas_only = lambda url, **kw: (
            {'chart': {'result': [{'timestamp': [close_ts], 'indicators': {'quote': [{'close': [22934.68]}]}}]}}
            if 'yahoo' in url else None
        )
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            Path(tmp1, '20261022.json').write_text(json.dumps(yahoo_only_doc), encoding='utf-8')
            Path(tmp2, '20261022.json').write_text(json.dumps(dom_doc), encoding='utf-8')
            with patch.object(ic, 'SPECS', spec):
                offline = ic.collect(lambda *a, **kw: None, now=now, db_dir=tmp2)[0]
                yahoo_self = ic.collect(live_overseas_only, now=now, db_dir=tmp1)[0]
                dom_verified = ic.collect(live_overseas_only, now=now, db_dir=tmp2)[0]
        # 1) 完全离线时不把旧库冒充实时源；2) 库内仅有 yahoo 时绝不自核验；3) 库内有当日境内源时完成独立对账
        self.assertFalse(offline['usable'])
        self.assertIsNone(offline['mainland_date'])
        self.assertFalse(yahoo_self['usable'])
        self.assertEqual(yahoo_self['status'], '单源待核验')
        self.assertTrue(dom_verified['usable'])
        self.assertEqual(dom_verified['status'], '双源一致')


if __name__ == '__main__':
    unittest.main()
