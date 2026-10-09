# Wealth Advisor Assistant

A lightweight, simulated multi-agent system for the AI Engineer (Agent Systems) assessment. It validates client financial JSON, retrieves mock CRM context, detects unusual transactions and financial risk signals, and produces structured recommendations for human review.

**Python 3.10+ only. No dependencies, API keys, external services, or paid APIs.** This is a deterministic agent simulation, not an LLM application. Mock data and simulated APIs are permitted by the assignment.

## Quick start

Open a terminal in this directory (the directory containing this README):

```sh
python --version
python -m wealth_advisor run --input examples/client.json --output result.json
python -m unittest discover -s tests -v
```

On Windows, `py -3` may be used instead of `python`. On Linux/macOS, use `python3` if needed. Nothing needs to be installed with pip. All paths in commands are relative to this project directory.

The run prints JSON and writes `result.json`. Expected sample findings:

| Finding | Evidence |
| --- | --- |
| Monthly surplus | INR 40,000 |
| Emergency fund coverage | 2 months, below the 3-month rule |
| Concentration | Equity accounts for 90% of holdings |
| Risk mismatch | Mock CRM marks the client conservative; equity exceeds 50% |
| Unusual debit | T005 is INR 50,000; same-category peer median is INR 1,050 |

The output status is `pending_review`; no investment transaction is executed. See [sample output](examples/output.json) for a real generated result. Run IDs and timestamps change on every execution. Repeated runs also retrieve historical summaries from local memory.

Additional generated examples show [CRM failure fallback](examples/fallback-output.json), [human override](examples/reviewed-output.json), and [execution logs](examples/execution.jsonl). Example run IDs are snapshots; run the demo to get a run ID present in your own local database before reviewing it.

## Architecture and interactions

```text
JSON input -> validation -> OrchestratorAgent
                           |
                           +-> DataFetcherAgent -> CRMTool + MemoryTool
                           +-> AnalyzerAgent    -> AnalysisTool
                           +-> AdvisoryAgent    -> recommendations
                           |
                           +-> pending_review -> MemoryTool
                                  |
                          human approve / reject / override

EventTool records execution, decisions, errors, and review transitions.
```

The orchestrator owns the execution order and failure boundaries. Each specialized agent implements the `Agent` protocol and receives a per-run `Session` and injected `Tools`. The data fetcher enriches validated inputs with risk tolerance, goals, and historical summaries. The analyzer invokes a replaceable analysis tool. The advisory agent turns signals into explainable next steps, including follow-up on signals seen in the previous run.

Agents do not instantiate adapters or make raw API calls. Protocols in `contracts.py` define CRM, analysis, memory, and logging interfaces; `build_system()` is the composition root. The in-process `MockCRM.fetch()` simulates `GET /clients/{id}`. Replacing it with a real HTTP adapter only requires implementing `CRMTool.fetch()` and injecting that adapter; this submission makes no actual network requests.

| File | Responsibility |
| --- | --- |
| `wealth_advisor/contracts.py` | Agent/tool protocols and short-term session memory |
| `wealth_advisor/validation.py` | Financial input validation |
| `wealth_advisor/agents.py` | Three specialized agents |
| `wealth_advisor/analysis.py` | Explainable anomaly and risk rules |
| `wealth_advisor/tools.py` | Mock CRM, SQLite memory, JSON event logging |
| `wealth_advisor/system.py` | Orchestration, fallback handling, human review |
| `wealth_advisor/__main__.py` | CLI entry point |
| `tests/` | Unit and command-line integration tests |

## Input contract and assumptions

All fields in `examples/client.json` are required. Monetary values must be zero or finite JSON numbers between 0.01 and 1e15 per value; this demo assumes a smallest nonzero amount of one hundredth of the reported currency unit. Booleans and numeric strings are rejected. Income/expenses are reported monthly amounts, not totals inferred from the transaction sample. Transactions may be a partial history. Amounts are nonnegative magnitudes and `direction` is `debit` or `credit`. Transaction IDs must be unique and dates must be valid `YYYY-MM-DD`. Empty holdings/transactions are allowed and produce limitations. Unknown input fields are ignored.

All amounts are assumed to use the single reported three-letter uppercase currency code. Currency conversion and real market data are outside scope. Liquid assets are reported separately; they are not added to holdings for allocation calculations. Asset classes/categories are case-sensitive (`equity` is used for the risk rule). Holding rows in the same asset class are aggregated before concentration checks. Missing CRM clients use an unknown profile rather than inventing a risk tolerance. The mock CRM contains only C001 with a conservative profile and sample goals.

## Anomaly detection and financial signals

For each debit category with at least five transactions, each candidate is compared with its other category peers. The baseline excludes the candidate. Let `m` be the peer median and `MAD` the median absolute deviation from `m`:

```text
threshold = max(3 * m, m + 6 * 1.4826 * MAD)
flag when amount > threshold AND amount > 10% of reported monthly income
```

This handles a zero MAD without dividing by zero and avoids flagging large credits as unusual spending. Each signal includes its evidence and threshold. Categories with too few debit observations produce a limitation instead of a fabricated statistical result. The rule detects unusually large debits; it does not classify fraud or detect every kind of anomaly. Multiple outliers can contaminate a small baseline.

Other rules detect negative monthly cash flow, liquidity below three months, any asset class above 70%, conservative equity exposure above 50%, and debt above twelve months of income (when income is positive). Thresholds are explicit demo heuristics, not calibrated investment suitability standards. Zero expenses produce `null` coverage and a limitation. No positive holdings produce an empty allocation and a limitation.

## Failures and observability

Simulate an API failure or a missing CRM record:

```sh
python -m wealth_advisor run --input examples/client.json --crm-mode fail
python -m wealth_advisor run --input examples/client.json --crm-mode missing
```

Both continue with `source: fallback`, unknown risk tolerance, a warning, and `data_quality: degraded`. Missing/malformed input or invalid financial fields produce structured error JSON and exit code 1. Unexpected agent failures stop the workflow with `agent_failed` rather than output incomplete advice. Successful analysis, including degraded results, returns exit code 0. Argument syntax errors use argparse's normal help/error behavior and exit code 2.

Memory read failures, including malformed historical records, continue without history. The memory adapter translates storage-specific exceptions into the shared `ToolError` contract so agents do not depend on SQLite. Memory save failures return the analysis with `memory_saved: false` and a warning; such runs cannot be reviewed by ID until storage is fixed and analysis rerun. Logging write failures emit a minimal stderr event and do not terminate analysis. There are no automatic retries for mock failures; real adapters should implement bounded retry/timeouts appropriate to their API.

Default logs are at `.state/execution.jsonl`. Each event carries a timestamp and run ID. Events cover agent starts/completions, signal decisions, tool fallbacks, validation errors, and review decisions. Financial amounts and full client payloads are not logged. SQLite stores output reports locally in `.state/memory.sqlite3`; it is not encrypted. Use synthetic data for this demo.

## Memory and human review

`Session` is isolated short-term memory. SQLite persists reports and returns up to five recent summaries for the same client ID. Historical reports from other client IDs are excluded. Use `--state-dir` on both commands to select the same alternative memory directory.

Copy the `run_id` from your analysis result and replace `RUN_ID` below:

```sh
python -m wealth_advisor review --run-id RUN_ID --decision approve --reviewer "Advisor" --notes "Validated input and recommendations" --output approved.json
python -m wealth_advisor review --run-id RUN_ID --decision reject --reviewer "Advisor" --notes "Need supporting documents"
python -m wealth_advisor review --run-id RUN_ID --decision override --reviewer "Advisor" --notes "Adjusted after client meeting" --recommendations examples/override.json --output overridden.json
```

Choose one decision per run. Only pending runs can transition; repeated review is rejected. Review transitions use a SQLite transaction so simultaneous reviews cannot overwrite each other. Reviewer, notes, decision, and timestamp are persisted. Override preserves the original recommendations in the review record. Approval means manual validation, not execution of a trade. This CLI checkpoint has no authentication; production would require authenticated reviewers, authorization, and protected audit storage.

## Decisions and trade-offs

- Deterministic agents make the output reproducible, free, and easy to inspect. There is no language model, autonomous planning, or natural-language chat; reasoning is explicit code and rules.
- Three agents provide clear fetching, analysis, and advisory boundaries without a framework dependency. Sequential execution keeps the flow easy to debug.
- Mock CRM makes the evaluation run offline and demonstrates controlled API failures. It omits real network authentication, retry, and schema/version complexity.
- Robust, explainable rules need no training data but miss patterns a trained model could detect. Sparse histories are explicitly marked as limited.
- SQLite supplies persistent memory and atomic review updates without running a database service. It suits a local demo, not a multi-user deployment.
- A CLI focuses on the assignment's system design requirements. No dashboard or paid hosting is required.

## Verification and requirement mapping

Run `python -m unittest discover -s tests -v`. Tests cover normal routing, anomalies including zero MAD and sparse history, cash flow/debt/aggregated holdings, degraded or malformed CRM context, strict input validation, zero/empty data, memory persistence and client isolation, corrupted storage, processing failures, human approval/rejection/override and competing reviewers, immutable inputs, event logs, and the CLI. Integration tests invoke the actual CLI as a subprocess.

| Assignment requirement | Implementation |
| --- | --- |
| Orchestrator routes tasks/manages flow | `OrchestratorAgent.run()` |
| At least two specialized agents | DataFetcherAgent, AnalyzerAgent, AdvisoryAgent |
| Clean tool interfaces | Protocols and injected Tools |
| Client JSON and CRM context | Validation and MockCRM |
| Anomaly detection and insights | RuleAnalysis with evidence and AdvisoryAgent |
| Graceful errors and fallback | Structured errors, degraded context, memory/log handling |
| Execution/decision/error logging | JSON event stream with correlated run IDs |
| Short/long-term memory bonus | Session and SQLiteMemory |
| Human checkpoint bonus | Persisted approve/reject/override CLI |
| Sample input/output and run guide | examples/ and this README |

## Submission

Upload the contents of **this directory** to a new public GitHub repository. Include source code, tests, README, and `examples/`. Do not upload `.state/`, temporary test data, or real client information. No build step or dependency download is needed. Open the repository link while logged out to verify it is accessible, then paste that repository URL into the assessment form. A local folder path is not a submission link.
