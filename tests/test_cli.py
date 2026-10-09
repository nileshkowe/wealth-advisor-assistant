import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CLITests(unittest.TestCase):
    def setUp(self):
        self.project = Path(__file__).resolve().parents[1]
        root = self.project / '.test-state'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'wealth_advisor', *args],
                              cwd=self.project, capture_output=True, text=True)

    def test_demo_then_review(self):
        run = self.cli('run', '--input', 'examples/client.json', '--state-dir', str(self.state))
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result['status'], 'pending_review')
        review = self.cli('review', '--run-id', result['run_id'], '--decision', 'approve',
                          '--reviewer', 'Test advisor', '--notes', 'Verified',
                          '--state-dir', str(self.state))
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertEqual(json.loads(review.stdout)['status'], 'approved')

    def test_missing_file_and_malformed_json(self):
        result = self.cli('run', '--input', str(self.state / 'absent.json'))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'error')
        path = self.state / 'bad.json'
        path.write_text('{broken', encoding='utf-8')
        result = self.cli('run', '--input', str(path))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['errors'][0]['code'], 'cli_error')

    def test_failed_crm_and_output_file(self):
        output = self.state / 'nested' / 'result.json'
        result = self.cli('run', '--input', 'examples/client.json', '--crm-mode', 'fail',
                          '--state-dir', str(self.state), '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text())['context']['source'], 'fallback')


if __name__ == '__main__':
    unittest.main()
