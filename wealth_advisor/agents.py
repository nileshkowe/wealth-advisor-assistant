"""Specialized agents exchange data through session memory and tool interfaces."""
from .contracts import Session, Tools, ToolError


class DataFetcherAgent:
    name = 'data_fetcher'

    def execute(self, session: Session, tools: Tools) -> None:
        try:
            context = tools.crm.fetch(session.client['client_id'])
            if not isinstance(context, dict) or context.get('risk_tolerance') not in ('conservative', 'moderate', 'aggressive'):
                raise ValueError('CRM returned an invalid risk profile')
            if not isinstance(context.get('goals'), list) or not all(isinstance(g, str) for g in context['goals']):
                raise ValueError('CRM returned invalid goals')
            session.context = context
        except (ConnectionError, TimeoutError, LookupError, ValueError, OSError) as error:
            session.context = {'risk_tolerance': 'unknown', 'goals': [], 'source': 'fallback'}
            session.warnings.append('CRM context unavailable; confirm risk tolerance and goals manually.')
            tools.events.emit(session.run_id, 'tool_fallback', tool='crm', error_type=type(error).__name__)
        try:
            session.history = tools.memory.recent(session.client['client_id'])
        except (OSError, ValueError, RuntimeError, ToolError) as error:
            session.warnings.append('Historical memory unavailable; continuing with current input.')
            tools.events.emit(session.run_id, 'tool_fallback', tool='memory', error_type=type(error).__name__)


class AnalyzerAgent:
    name = 'analyzer'

    def execute(self, session: Session, tools: Tools) -> None:
        session.analysis = tools.analysis.analyze(session.client, session.context)
        session.warnings.extend(session.analysis['limitations'])
        tools.events.emit(session.run_id, 'analysis_decision',
                          signal_codes=[s['code'] for s in session.analysis['signals']])


class AdvisoryAgent:
    name = 'advisory'

    def execute(self, session: Session, tools: Tools) -> None:
        actions = {
            'negative_cash_flow': 'Review recurring expenses and agree a budget to restore positive monthly cash flow.',
            'low_liquidity': 'Discuss building liquid reserves toward at least three months of reported expenses.',
            'concentration': 'Review asset-class concentration and discuss diversification after confirming goals.',
            'risk_mismatch': 'Validate the CRM risk profile and review equity exposure with the advisor.',
            'high_debt': 'Review debt balances, interest rates, and repayment priorities with the advisor.',
            'unusual_transaction': 'Verify flagged transaction IDs and supporting records with the client before treating them as suspicious.',
        }
        codes = {signal['code'] for signal in session.analysis['signals']}
        session.recommendations = [message for code, message in actions.items() if code in codes]
        if session.context['risk_tolerance'] == 'unknown':
            session.recommendations.insert(0, 'Confirm client risk tolerance and goals before any allocation decision.')
        if session.warnings:
            session.recommendations.append('Resolve the reported data limitations before finalizing advice.')
        if not session.recommendations:
            session.recommendations = ['No configured rule triggered; validate completeness and schedule a routine advisor review.']
        if session.history:
            previous = set(session.history[0]['signal_codes'])
            persistent = sorted(codes & previous)
            if persistent:
                session.recommendations.append('Follow up on recurring signals from the last run: ' + ', '.join(persistent) + '.')
