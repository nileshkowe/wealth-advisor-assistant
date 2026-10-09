"""Orchestrator controls routing, error boundaries, persistence and review."""
from pathlib import Path
from uuid import uuid4
from .contracts import Agent, Session, Tools
from .validation import validate
from .tools import JsonEvents, MockCRM, SQLiteMemory, utc_now
from .analysis import RuleAnalysis
from .agents import DataFetcherAgent, AnalyzerAgent, AdvisoryAgent


class OrchestratorAgent:
    def __init__(self, tools: Tools, agents: list[Agent]):
        self.tools = tools
        self.agents = agents

    def run(self, raw):
        run_id = str(uuid4())
        result = {'schema_version': '1.0', 'run_id': run_id, 'created_at': utc_now(),
                  'status': 'error', 'execution': [], 'errors': []}
        self.tools.events.emit(run_id, 'run_started')
        try:
            client = validate(raw)
        except (ValueError, TypeError) as error:
            result['errors'] = [{'code': 'invalid_input', 'message': str(error)}]
            self.tools.events.emit(run_id, 'validation_failed', error_type=type(error).__name__)
            return result
        session = Session(run_id, client)
        for agent in self.agents:
            self.tools.events.emit(run_id, 'agent_started', agent=agent.name)
            try:
                agent.execute(session, self.tools)
            except Exception as error:
                # Final safety boundary; do not manufacture advice from incomplete analysis.
                result['errors'] = [{'code': 'agent_failed', 'message': f'{agent.name} failed; inspect execution logs.'}]
                self.tools.events.emit(run_id, 'agent_failed', agent=agent.name, error_type=type(error).__name__)
                return result
            result['execution'].append(agent.name)
            self.tools.events.emit(run_id, 'agent_completed', agent=agent.name)
        result.update(client_id=client['client_id'], currency=client['currency'],
                      status='pending_review', context=session.context, history=session.history,
                      analysis=session.analysis, recommendations=session.recommendations,
                      warnings=session.warnings, data_quality='degraded' if session.warnings else 'complete',
                      review=None, memory_saved=True)
        try:
            self.tools.memory.save(result)
        except (OSError, ValueError, RuntimeError) as error:
            result['memory_saved'] = False
            result['data_quality'] = 'degraded'
            result['warnings'].append('Memory save failed; this run cannot be reviewed by run ID until rerun with working storage.')
            self.tools.events.emit(run_id, 'tool_fallback', tool='memory_save', error_type=type(error).__name__)
        self.tools.events.emit(run_id, 'review_required', status=result['status'])
        self.tools.events.emit(run_id, 'run_completed', status=result['status'])
        return result

    def review(self, run_id, decision, reviewer, notes, recommendations=None):
        if decision not in ('approve', 'reject', 'override'):
            raise ValueError('Decision must be approve, reject or override')
        if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(notes, str) or not notes.strip():
            raise ValueError('Reviewer and notes are required')
        if decision == 'override':
            if not isinstance(recommendations, list) or not recommendations or not all(isinstance(r, str) and r.strip() for r in recommendations):
                raise ValueError('Override requires a nonempty array of recommendation strings')
        elif recommendations is not None:
            raise ValueError('Replacement recommendations are only allowed for override')
        checkpoint = {'decision': decision, 'reviewer': reviewer.strip(), 'notes': notes.strip(),
                      'reviewed_at': utc_now()}
        if decision == 'override':
            checkpoint['recommendations'] = [r.strip() for r in recommendations]
        result = self.tools.memory.review(run_id, checkpoint)
        self.tools.events.emit(run_id, 'human_review', decision=decision)
        return result


def build_system(state_dir, crm_mode='ok'):
    path = Path(state_dir)
    tools = Tools(MockCRM(crm_mode), RuleAnalysis(), SQLiteMemory(path / 'memory.sqlite3'),
                  JsonEvents(path / 'execution.jsonl'))
    return OrchestratorAgent(tools, [DataFetcherAgent(), AnalyzerAgent(), AdvisoryAgent()])
