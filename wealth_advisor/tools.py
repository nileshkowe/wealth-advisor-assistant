"""Concrete adapters; agents depend on the contracts, not these classes."""
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from .contracts import ToolError


def memory_operation(operation):
    """Translate storage and malformed-record errors at the adapter boundary."""
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (sqlite3.Error, OSError, KeyError, TypeError, ValueError) as error:
            raise ToolError(f'Memory operation {operation.__name__} failed ({type(error).__name__}).') from error
    return guarded


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class MockCRM:
    """In-process simulation of GET /clients/{id}; no external request or cost."""
    def __init__(self, mode='ok'):
        if mode not in ('ok', 'fail', 'missing'):
            raise ValueError('Unsupported CRM mode')
        self.mode = mode

    def fetch(self, client_id):
        if self.mode == 'fail':
            raise ConnectionError('Simulated CRM unavailable')
        if self.mode == 'missing' or client_id != 'C001':
            raise LookupError('Client absent from simulated CRM')
        return {'risk_tolerance': 'conservative',
                'goals': ['Preserve capital', 'Build emergency savings'],
                'source': 'mock_crm'}


class JsonEvents:
    def __init__(self, path):
        self.path = Path(path)

    def emit(self, run_id, event, **details):
        row = {'timestamp': utc_now(), 'run_id': run_id, 'event': event, **details}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as file:
                file.write(json.dumps(row, allow_nan=False) + '\n')
        except OSError:
            # Observability storage failure must not terminate financial analysis.
            import sys
            print(json.dumps({'run_id': run_id, 'event': 'log_write_failed'}), file=sys.stderr)


class SQLiteMemory:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS runs '
                               '(run_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, '
                               'created_at TEXT NOT NULL, payload TEXT NOT NULL)')
            with connection:
                yield connection
        finally:
            connection.close()

    @memory_operation
    def recent(self, client_id):
        with self.connect() as connection:
            rows = connection.execute('SELECT payload FROM runs WHERE client_id=? '
                                      'ORDER BY created_at DESC, rowid DESC LIMIT 5', (client_id,)).fetchall()
        summaries = []
        for (payload,) in rows:
            result = json.loads(payload)
            summaries.append({'run_id': result['run_id'], 'status': result['status'],
                              'created_at': result['created_at'],
                              'signal_codes': sorted({s['code'] for s in result['analysis']['signals']})})
        return summaries

    @memory_operation
    def save(self, result):
        with self.connect() as connection:
            connection.execute('INSERT INTO runs VALUES (?, ?, ?, ?)',
                (result['run_id'], result['client_id'], result['created_at'],
                 json.dumps(result, allow_nan=False)))

    @memory_operation
    def get(self, run_id):
        with self.connect() as connection:
            row = connection.execute('SELECT payload FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if not row:
            raise ValueError('Run not found in memory')
        return json.loads(row[0])

    @memory_operation
    def review(self, run_id, decision):
        with self.connect() as connection:
            # Serialize review transitions to prevent competing reviewers from overwriting.
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT payload FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if not row:
                raise ValueError('Run not found in memory')
            result = json.loads(row[0])
            if result['status'] != 'pending_review':
                raise ValueError('Only pending runs can be reviewed')
            if decision['decision'] == 'override':
                decision['original_recommendations'] = result['recommendations'][:]
                result['recommendations'] = decision['recommendations'][:]
            result['review'] = decision
            result['status'] = {'approve': 'approved', 'reject': 'rejected',
                                'override': 'overridden'}[decision['decision']]
            connection.execute('UPDATE runs SET payload=? WHERE run_id=?',
                               (json.dumps(result, allow_nan=False), run_id))
        return result
