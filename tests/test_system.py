import copy
import json
from pathlib import Path
import tempfile
import unittest

from wealth_advisor.system import build_system


def client():
    return {
        'client_id': 'C001', 'currency': 'INR',
        'monthly_income': 100000, 'monthly_expenses': 60000,
        'liquid_assets': 120000, 'debt': 50000,
        'holdings': [{'asset_class': 'equity', 'value': 900000},
                     {'asset_class': 'bonds', 'value': 100000}],
        'transactions': [
            {'id': str(i), 'date': '2026-09-01', 'amount': a,
             'direction': 'debit', 'category': 'shopping'}
            for i, a in enumerate([900, 1000, 1100, 1200, 50000])
        ],
    }


class SystemTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / '.test-state'
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_system(self, data=None, **options):
        return build_system(self.root, **options).run(client() if data is None else data)

    def test_flow_and_signals(self):
        result = self.run_system()
        self.assertEqual(result['status'], 'pending_review')
        self.assertEqual(result['analysis']['metrics']['monthly_surplus'], 40000)
        self.assertEqual(result['analysis']['metrics']['emergency_fund_months'], 2)
        codes = {a['code'] for a in result['analysis']['signals']}
        self.assertTrue({'unusual_transaction', 'low_liquidity', 'concentration'} <= codes)
        self.assertEqual(result['execution'], ['data_fetcher', 'analyzer', 'advisory'])
        self.assertTrue(result['recommendations'])

    def test_crm_failure_is_degraded_and_still_analyzes(self):
        result = self.run_system(crm_mode='fail')
        self.assertEqual(result['data_quality'], 'degraded')
        self.assertEqual(result['context']['risk_tolerance'], 'unknown')
        self.assertTrue(result['warnings'])
        self.assertEqual(result['status'], 'pending_review')

    def test_invalid_input_has_structured_error(self):
        for data in [None, [], {}, {'client_id': 'C001'},
                     dict(client(), monthly_income=-1),
                     dict(client(), liquid_assets=float('nan')),
                     dict(client(), monthly_expenses=True)]:
            with self.subTest(data=data):
                result = build_system(self.root).run(data)
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['errors'][0]['code'], 'invalid_input')

    def test_transaction_validation(self):
        for change in [{'amount': 'bad'}, {'date': '2026-99-99'},
                       {'direction': 'other'}, {'amount': -1}]:
            data = client()
            data['transactions'][0].update(change)
            self.assertEqual(self.run_system(data)['status'], 'error')
        data = client()
        data['transactions'][1]['id'] = '0'
        self.assertEqual(self.run_system(data)['status'], 'error')

    def test_empty_and_zero_data_is_safe(self):
        data = client()
        data.update(transactions=[], holdings=[], monthly_expenses=0, liquid_assets=0)
        result = self.run_system(data)
        self.assertEqual(result['status'], 'pending_review')
        self.assertIsNone(result['analysis']['metrics']['emergency_fund_months'])
        json.dumps(result, allow_nan=False)

    def test_memory_retrieval_and_client_isolation(self):
        first = self.run_system()
        second = self.run_system()
        self.assertEqual(second['history'][0]['run_id'], first['run_id'])
        data = client()
        data['client_id'] = 'OTHER'
        self.assertEqual(self.run_system(data)['history'], [])

    def test_review_approval_rejection_override(self):
        system = build_system(self.root)
        result = system.run(client())
        approved = system.review(result['run_id'], 'approve', 'Advisor', 'Checked data')
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['review']['reviewer'], 'Advisor')
        with self.assertRaises(ValueError):
            system.review(result['run_id'], 'reject', 'Advisor', 'Again')
        result = system.run(client())
        rejected = system.review(result['run_id'], 'reject', 'Advisor', 'Need documents')
        self.assertEqual(rejected['status'], 'rejected')
        result = system.run(client())
        overridden = system.review(result['run_id'], 'override', 'Advisor', 'Validated',
                                   ['Arrange a follow-up meeting.'])
        self.assertEqual(overridden['status'], 'overridden')
        self.assertEqual(overridden['recommendations'], ['Arrange a follow-up meeting.'])
        self.assertTrue(overridden['review']['original_recommendations'])

    def test_review_validation(self):
        system = build_system(self.root)
        result = system.run(client())
        for args in [('approve', '', 'notes', None),
                     ('override', 'Advisor', 'notes', []),
                     ('invalid', 'Advisor', 'notes', None)]:
            with self.assertRaises(ValueError):
                system.review(result['run_id'], *args)

    def test_memory_failure_is_nonfatal(self):
        system = build_system(self.root)
        def broken(*args):
            raise OSError('Unavailable')
        system.tools.memory.recent = broken
        system.tools.memory.save = broken
        result = system.run(client())
        self.assertEqual(result['status'], 'pending_review')
        self.assertEqual(result['data_quality'], 'degraded')
        self.assertTrue(any('memory' in w.lower() for w in result['warnings']))

    def test_input_not_mutated_and_credit_not_flagged(self):
        data = client()
        data['transactions'][-1]['direction'] = 'credit'
        original = copy.deepcopy(data)
        result = self.run_system(data)
        self.assertEqual(data, original)
        self.assertFalse(any(a['code'] == 'unusual_transaction'
                             for a in result['analysis']['signals']))

    def test_logs_have_flow_without_financial_payload(self):
        self.run_system()
        rows = [json.loads(line) for line in (self.root / 'execution.jsonl').read_text().splitlines()]
        self.assertTrue(any(r['event'] == 'agent_completed' for r in rows))
        self.assertTrue(all('run_id' in r for r in rows))
        self.assertNotIn('monthly_income', json.dumps(rows))

    def test_cash_flow_debt_and_aggregated_holdings(self):
        data = client()
        data.update(monthly_income=10000, debt=200000)
        data['holdings'] = [{'asset_class': 'equity', 'value': 45},
                            {'asset_class': 'equity', 'value': 45},
                            {'asset_class': 'bonds', 'value': 10}]
        result = self.run_system(data)
        codes = {a['code'] for a in result['analysis']['signals']}
        self.assertTrue({'negative_cash_flow', 'high_debt', 'concentration', 'risk_mismatch'} <= codes)
        self.assertEqual(result['analysis']['metrics']['allocation']['equity'], 0.9)

    def test_zero_mad_and_sparse_history(self):
        data = client()
        for row in data['transactions'][:-1]:
            row['amount'] = 1000
        result = self.run_system(data)
        anomaly = next(s for s in result['analysis']['signals'] if s['code'] == 'unusual_transaction')
        self.assertEqual(anomaly['evidence']['threshold'], 3000)
        data['transactions'] = data['transactions'][-1:]
        result = self.run_system(data)
        self.assertFalse(any(s['code'] == 'unusual_transaction' for s in result['analysis']['signals']))
        self.assertTrue(result['analysis']['limitations'])

    def test_missing_and_malformed_crm(self):
        result = self.run_system(crm_mode='missing')
        self.assertEqual(result['context']['source'], 'fallback')
        self.assertFalse(any(s['code'] == 'risk_mismatch' for s in result['analysis']['signals']))
        system = build_system(self.root)
        system.tools.crm.fetch = lambda _: {'risk_tolerance': 'invented'}
        self.assertEqual(system.run(client())['context']['source'], 'fallback')

    def test_corrupt_memory_falls_back(self):
        (self.root / 'memory.sqlite3').write_text('not a database')
        result = self.run_system()
        self.assertEqual(result['status'], 'pending_review')
        self.assertFalse(result['memory_saved'])

    def test_analysis_failure_does_not_produce_advice(self):
        system = build_system(self.root)
        def broken(*args):
            raise RuntimeError('Simulated processing error')
        system.tools.analysis.analyze = broken
        result = system.run(client())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['errors'][0]['code'], 'agent_failed')
        self.assertNotIn('recommendations', result)

    def test_repeated_signals_inform_advice(self):
        self.run_system()
        result = self.run_system()
        self.assertTrue(any('recurring signals' in r for r in result['recommendations']))

    def test_concurrent_review_only_one_succeeds(self):
        from concurrent.futures import ThreadPoolExecutor
        system = build_system(self.root)
        result = system.run(client())
        def review(name):
            try:
                return system.review(result['run_id'], 'approve', name, 'Reviewed')['status']
            except ValueError:
                return 'already_reviewed'
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(review, ['A', 'B']))
        self.assertCountEqual(statuses, ['approved', 'already_reviewed'])

    def test_subcent_money_rejected_with_valid_json(self):
        data = client()
        data['monthly_expenses'] = 5e-324
        result = self.run_system(data)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['errors'][0]['code'], 'invalid_input')
        json.dumps(result, allow_nan=False)

    def test_malformed_historical_payload_falls_back(self):
        system = build_system(self.root)
        first = system.run(client())
        with system.tools.memory.connect() as connection:
            connection.execute('UPDATE runs SET payload=? WHERE run_id=?', ('{}', first['run_id']))
        result = system.run(client())
        self.assertEqual(result['status'], 'pending_review')
        self.assertEqual(result['history'], [])
        self.assertTrue(any('memory unavailable' in w.lower() for w in result['warnings']))


if __name__ == '__main__':
    unittest.main()
