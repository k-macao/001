import sys
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
            return ic.collect(fetch, now=now or datetime(2026,10,21,tzinfo=timezone.utc))[0]

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
        self.assertEqual(self.run_case(now=datetime(2026,10,27,tzinfo=timezone.utc))['status'], '数据过期')

    def test_invalid_close(self):
        for close in ['nan', 'inf', '-1', '0']:
            self.assertFalse(self.run_case(em_close=close)['usable'])

    def test_intraday_filtered(self):
        self.assertEqual(ic._clean([('2026-10-21',100)], '^HSI', datetime(2026,10,21,3,tzinfo=timezone.utc)), {})

if __name__ == '__main__':
    unittest.main()
