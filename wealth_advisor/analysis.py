"""Explainable rules for a simulated advisor, not investment execution."""
from collections import defaultdict
from statistics import median


class RuleAnalysis:
    def analyze(self, client, context):
        income = client['monthly_income']
        expenses = client['monthly_expenses']
        liquidity = client['liquid_assets'] / expenses if expenses else None
        total = sum(h['value'] for h in client['holdings'])
        by_class = defaultdict(float)
        for holding in client['holdings']:
            by_class[holding['asset_class']] += holding['value']
        allocation = {key: round(value / total, 4) for key, value in sorted(by_class.items())} if total else {}
        signals = []

        def signal(code, severity, message, evidence):
            signals.append({'code': code, 'severity': severity,
                            'message': message, 'evidence': evidence})

        if expenses > income:
            signal('negative_cash_flow', 'high', 'Monthly expenses exceed income.',
                   {'shortfall': round(expenses - income, 2)})
        if liquidity is not None and liquidity < 3:
            signal('low_liquidity', 'medium', 'Liquid assets cover less than three months of expenses.',
                   {'months': round(liquidity, 2), 'threshold_months': 3})
        for key, value in by_class.items():
            if total and value / total > 0.7:
                signal('concentration', 'medium', 'More than 70% of holdings are in one asset class.',
                       {'asset_class': key, 'share': round(value / total, 4), 'threshold_share': 0.7})
        equity_share = by_class.get('equity', 0) / total if total else 0
        if context['risk_tolerance'] == 'conservative' and equity_share > 0.5:
            signal('risk_mismatch', 'high', 'Equity allocation exceeds the conservative demo threshold.',
                   {'equity_share': round(equity_share, 4), 'threshold_share': 0.5})
        if income > 0 and client['debt'] > income * 12:
            signal('high_debt', 'high', 'Debt exceeds twelve months of reported income.',
                   {'debt_to_annual_income': round(client['debt'] / (income * 12), 2)})
        groups = defaultdict(list)
        for row in client['transactions']:
            if row['direction'] == 'debit':
                groups[row['category']].append(row)
        for category, rows in groups.items():
            # Leave-one-out baseline prevents the candidate from diluting its own signal.
            if len(rows) < 5:
                continue
            for candidate in rows:
                baseline = [r['amount'] for r in rows if r['id'] != candidate['id']]
                typical = median(baseline)
                mad = median(abs(amount - typical) for amount in baseline)
                threshold = max(typical * 3, typical + 6 * 1.4826 * mad)
                if candidate['amount'] > threshold and candidate['amount'] > income * 0.1:
                    signal('unusual_transaction', 'high', 'Debit unusually large relative to its category peers.',
                           {'transaction_id': candidate['id'], 'category': category,
                            'amount': candidate['amount'], 'peer_median': typical,
                            'threshold': round(threshold, 2)})
        warnings = []
        if not total:
            warnings.append('No positive holding values; allocation risk cannot be assessed.')
        if not expenses:
            warnings.append('Zero monthly expenses; emergency fund coverage is undefined.')
        if not groups or any(len(rows) < 5 for rows in groups.values()):
            warnings.append('Category anomaly detection needs at least five debit transactions per category.')
        return {'metrics': {'monthly_surplus': round(income - expenses, 2),
                            'emergency_fund_months': round(liquidity, 2) if liquidity is not None else None,
                            'total_holdings': round(total, 2), 'allocation': allocation},
                'signals': signals, 'limitations': warnings}
