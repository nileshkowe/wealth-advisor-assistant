"""Strict validation at the input boundary; never silently discard bad rows."""
import copy
from datetime import date
import math
from typing import Any


def number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f'{label} must be a number')
    try:
        valid = math.isfinite(value) and (value == 0 or 0.01 <= value <= 1e15)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{label} must be zero or a finite number between 0.01 and 1e15')
    return float(value)


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f'{label} must be a nonempty string of at most 200 characters')
    return value.strip()


def validate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError('Client input must be a JSON object')
    # Copy only recognized fields so arbitrary extra payloads cannot enter memory.
    client = {'client_id': text(raw.get('client_id'), 'client_id'),
              'currency': text(raw.get('currency'), 'currency')}
    if len(client['currency']) != 3 or not client['currency'].isascii() or not client['currency'].isupper() or not client['currency'].isalpha():
        raise ValueError('currency must be a three-letter uppercase code')
    for key in ('monthly_income', 'monthly_expenses', 'liquid_assets', 'debt'):
        client[key] = number(raw.get(key), key)
    for key in ('holdings', 'transactions'):
        if not isinstance(raw.get(key), list):
            raise ValueError(f'{key} must be an array (an empty array is allowed)')
    client['holdings'] = []
    for row in raw['holdings']:
        if not isinstance(row, dict):
            raise ValueError('Each holding must be an object')
        client['holdings'].append({'asset_class': text(row.get('asset_class'), 'asset_class'),
                                   'value': number(row.get('value'), 'holding value')})
    client['transactions'] = []
    ids = set()
    for row in raw['transactions']:
        if not isinstance(row, dict):
            raise ValueError('Each transaction must be an object')
        identifier = text(row.get('id'), 'transaction id')
        if identifier in ids:
            raise ValueError('Transaction IDs must be unique')
        ids.add(identifier)
        day = text(row.get('date'), 'transaction date')
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError:
            raise ValueError('Transaction date must be a valid YYYY-MM-DD date') from None
        direction = row.get('direction')
        if direction not in ('debit', 'credit'):
            raise ValueError('Transaction direction must be debit or credit')
        client['transactions'].append({'id': identifier, 'date': day,
            'amount': number(row.get('amount'), 'transaction amount'),
            'direction': direction, 'category': text(row.get('category'), 'category')})
    return copy.deepcopy(client)
