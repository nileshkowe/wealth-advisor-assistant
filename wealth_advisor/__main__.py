"""Run with python -m wealth_advisor; stdout is always the JSON result."""
import argparse
import json
from pathlib import Path
import sqlite3
from .system import build_system


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description='Simulated wealth advisor multi-agent system')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Analyze client JSON and pause for human review')
    run.add_argument('--input', required=True)
    run.add_argument('--crm-mode', choices=['ok', 'fail', 'missing'], default='ok')
    review = commands.add_parser('review', help='Validate or override a pending run')
    review.add_argument('--run-id', required=True)
    review.add_argument('--decision', required=True, choices=['approve', 'reject', 'override'])
    review.add_argument('--reviewer', required=True)
    review.add_argument('--notes', required=True)
    review.add_argument('--recommendations', help='JSON file containing an array of replacement strings')
    for command in (run, review):
        command.add_argument('--state-dir', default='.state')
        command.add_argument('--output', help='Also write the result JSON to this file')
    args = parser.parse_args()
    try:
        system = build_system(args.state_dir, getattr(args, 'crm_mode', 'ok'))
        if args.command == 'run':
            result = system.run(load_json(args.input))
        else:
            replacements = load_json(args.recommendations) if args.recommendations else None
            result = system.review(args.run_id, args.decision, args.reviewer, args.notes, replacements)
        serialized = json.dumps(result, indent=2, allow_nan=False)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + '\n', encoding='utf-8')
    except (OSError, ValueError, sqlite3.Error) as error:
        result = {'status': 'error', 'errors': [{'code': 'cli_error', 'message': str(error)}]}
        serialized = json.dumps(result, indent=2)
    print(serialized)
    return 1 if result['status'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
