import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


class StructuredSearchResultTest(unittest.TestCase):
  def test_perf_parser_preserves_values_status_and_order(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as directory:
      perf_stat = Path(directory) / "perf.stat"
      perf_stat.write_text(
        "# started on Linux\n"
        "220.74;msec;task-clock;220741321;100.00;;\n"
        "602596299;;cycles;221521385;87.50;;\n"
        "<not counted>;;instructions;222192390;0.00;;\n"
        "<not supported>;;stall_backend_mem;;;\n",
        encoding="utf-8",
      )
      parsed = bench_util.parsePerfStat(perf_stat)

    self.assertEqual(["task-clock", "cycles", "instructions", "stall_backend_mem"], [event["name"] for event in parsed["events"]])
    self.assertEqual("msec", parsed["events"][0]["unit"])
    self.assertEqual(220741321, parsed["events"][0]["runtime_ns"])
    self.assertEqual(87.5, parsed["events"][1]["running_percent"])
    self.assertEqual(("not_counted", None), (parsed["events"][2]["status"], parsed["events"][2]["value"]))
    self.assertEqual(("not_supported", None), (parsed["events"][3]["status"], parsed["events"][3]["value"]))
    self.assertEqual(["# started on Linux"], parsed["metadata_lines"])

  def test_schema_configuration_summary_and_derived_metrics(self):
    bench_util = load_bench_util()
    competitor = make_competitor()
    summary = {"measuredTasks": 500, "measuredElapsedMS": 200.0, "qps": 2500.0, "avgCPUCores": -1.0}
    perf_data = {
      "events": [
        perf_event("task-clock", 400.0, unit="msec"),
        perf_event("cycles", 1000),
        perf_event("instructions", 2500),
      ],
      "metadata_lines": [],
    }
    result = bench_util.buildHardwareResult(competitor, 3, 123, 456, summary, True, ("cycles", "instructions"), perf_data)

    self.assertEqual(1, result["schema_version"])
    self.assertEqual(
      {
        "mode": "search", "source": "wikimedium10k", "index": "/index", "queries": ["HighTerm"],
        "seed": -7, "query_concurrency": 2, "search_concurrency": 0, "warmup_repetitions": 20,
        "measured_repetitions": 50, "tasks_per_category": 10, "measured_tasks": 500,
        "measured_elapsed_sec": 0.2, "qps": 2500.0, "hardware_summary": True, "static_seed": 456,
      },
      result["benchmark"],
    )
    self.assertEqual({"competitor": "candidate", "iteration": 3, "seed": 123}, result["run"])
    self.assertEqual(["cycles", "instructions"], result["perf"]["requested_events"])
    self.assertEqual(2.5, result["derived"]["ipc"])
    self.assertEqual(2.0, result["derived"]["cycles_per_query"])
    self.assertEqual(5.0, result["derived"]["instructions_per_query"])
    self.assertEqual(2.0, result["derived"]["effective_cpu_count"])

  def test_multiplexed_counted_events_remain_usable_and_preserve_percentage(self):
    bench_util = load_bench_util()
    perf_data = {
      "events": [perf_event("cycles", 1000, running_percent=75.0), perf_event("instructions", 2500)],
      "metadata_lines": [],
    }
    result = bench_util.buildHardwareResult(
      make_competitor(), 0, 1, 2,
      {"measuredTasks": 10, "measuredElapsedMS": 100.0, "qps": 100.0, "avgCPUCores": -1.0},
      True, ("cycles", "instructions"), perf_data,
    )
    self.assertEqual(75.0, result["perf"]["events"][0]["running_percent"])
    self.assertEqual(2.5, result["derived"]["ipc"])
    self.assertEqual(100.0, result["derived"]["cycles_per_query"])

  def test_missing_events_make_derived_metrics_null(self):
    bench_util = load_bench_util()
    result = bench_util.buildHardwareResult(
      make_competitor(), 0, 1, 2,
      {"measuredTasks": 10, "measuredElapsedMS": 100.0, "qps": 100.0, "avgCPUCores": -1.0},
      False, ("cycles",), None,
    )
    self.assertEqual(
      {"ipc": None, "cycles_per_query": None, "instructions_per_query": None, "effective_cpu_count": None},
      result["derived"],
    )

  def test_successful_organized_summary_publishes_atomic_json(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      output, result_path = run_summary(bench_util, run_directory, exit_status=0)
      value = json.loads(Path(result_path).read_text(encoding="utf-8"))

    self.assertEqual(10, value["benchmark"]["measured_tasks"])
    self.assertEqual(2.0, value["benchmark"]["measured_elapsed_sec"])
    self.assertEqual(5.0, value["benchmark"]["qps"])
    self.assertEqual(2, value["benchmark"]["static_seed"])
    self.assertEqual(1, value["run"]["seed"])
    self.assertEqual(["cycles", "instructions"], [event["name"] for event in value["perf"]["events"]])
    self.assertIn(f"result: {result_path}", output)
    self.assertEqual("result.json", os.path.basename(result_path))
    self.assertEqual("iteration-0", os.path.basename(os.path.dirname(result_path)))

  def test_failed_benchmark_does_not_publish_json(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      with self.assertRaises(RuntimeError):
        run_summary(bench_util, run_directory, exit_status=1)
      self.assertFalse(os.path.exists(os.path.join(run_directory, "candidate", "iteration-0", "result.json")))

  def test_competitors_publish_only_their_own_summary_and_perf_values(self):
    bench_util = load_bench_util()
    baseline = make_competitor("baseline")
    candidate = make_competitor("my_modified_version")
    with tempfile.TemporaryDirectory() as run_directory:
      run_summary(bench_util, run_directory, competitor=baseline, measured_tasks=11, elapsed_ms=1100.0, qps=10.0, cycles=111)
      run_summary(bench_util, run_directory, competitor=candidate, measured_tasks=22, elapsed_ms=2000.0, qps=11.0, cycles=222)
      baseline_result = json.loads(Path(run_directory, "baseline", "iteration-0", "result.json").read_text(encoding="utf-8"))
      candidate_result = json.loads(Path(run_directory, "my_modified_version", "iteration-0", "result.json").read_text(encoding="utf-8"))

    self.assertEqual(("baseline", 11, 111), result_identity(baseline_result))
    self.assertEqual(("my_modified_version", 22, 222), result_identity(candidate_result))

  def test_legacy_run_has_no_structured_result_path(self):
    bench_util = load_bench_util()
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    runner.outputDir = None
    self.assertIsNone(runner.getSearchResultJSONPath(0, make_competitor()))


def perf_event(name, value, unit=None, running_percent=100.0):
  return {
    "name": name, "value": value, "unit": unit, "runtime_ns": 100,
    "running_percent": running_percent, "status": "counted",
  }


def make_competitor(name="candidate"):
  competition = types.SimpleNamespace(
    taskRepeatCount=20, taskCountPerCat=10, groupByCat=False,
    warmupTaskRepeatCount=20, measuredTaskRepeatCount=50,
    perfControl=True, perfEvents=("cycles", "instructions"), hardwareSummary=True,
    requestedTaskCategories=("HighTerm",), randomSeed=-7,
  )
  index = types.SimpleNamespace(
    getPath=lambda: "/index", facets=None,
    dataSource=types.SimpleNamespace(name="wikimedium10k"),
  )
  return types.SimpleNamespace(
    checkout="checkout", name=name, doSort=False, javaCommand="java", directory="MMapDirectory",
    index=index, analyzer="analyzer", tasksFile="tasks", numConcurrentQueries=2, competition=competition,
    searchConcurrency=0, similarity="similarity", commitPoint="multi", hiliteImpl="hilite", topN=10,
    testContext="", printHeap=False, pk=False, loadStoredFields=False, vectorDict=None, vectorFileName=None,
    vectorScale=None, exitable=False, pollute=False,
  )


def load_bench_util():
  pwd = types.ModuleType("pwd")
  pwd.getpwuid = lambda unused_uid: types.SimpleNamespace(pw_name="test")
  localconstants = types.ModuleType("localconstants")
  localconstants.BASE_DIR = tempfile.gettempdir()
  sys.modules.pop("benchUtil", None)
  sys.modules.pop("constants", None)
  with mock.patch.dict(sys.modules, {"localconstants": localconstants, "pwd": pwd}):
    import benchUtil
  return benchUtil


def run_summary(bench_util, run_directory, exit_status=0, competitor=None, measured_tasks=10, elapsed_ms=2000.0, qps=5.0, cycles=1000):
  if competitor is None:
    competitor = make_competitor()
  runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
  runner.verbose = False
  runner.outputDir = run_directory

  class Process:
    stdout = io.BytesIO(b"---- MEASURED PHASE READY ----\n---- MEASURED PHASE COMPLETE ----\n")

    def wait(self):
      return exit_status

  def fake_popen(command, **unused_kwargs):
    result_log = Path(command[command.index("-log") + 1])
    result_log.write_text(
      f"Hardware summary measured tasks: {measured_tasks}\n"
      f"Hardware summary measured elapsed msec: {elapsed_ms}\n"
      f"Hardware summary QPS: {qps}\n"
      "Average CPU cores used: -1.0\n",
      encoding="utf-8",
    )
    perf_path = Path(command[command.index("-o") + 1])
    perf_path.write_text(
      f"{cycles};;cycles;100;100.00;;\n2000;;instructions;100;100.00;;\n",
      encoding="utf-8",
    )
    return Process()

  class ControlResources:
    controlPath = "control"
    ackPath = "ack"

    def __init__(self, unused_enabled):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *unused_args):
      pass

  output = io.StringIO()
  with (
    mock.patch.object(bench_util, "PERF_EXE", "perf"),
    mock.patch.object(bench_util, "PerfControlResources", ControlResources),
    mock.patch.object(bench_util, "getClassPath", return_value=[]),
    mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
    mock.patch.object(bench_util, "get_profiler_jvm_args", return_value="JFR"),
    mock.patch.object(bench_util.subprocess, "Popen", side_effect=fake_popen),
    contextlib.redirect_stdout(output),
  ):
    if exit_status == 0:
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
    else:
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
  return output.getvalue(), runner.getSearchResultJSONPath(0, competitor)


def result_identity(result):
  cycles = next(event["value"] for event in result["perf"]["events"] if event["name"] == "cycles")
  return result["run"]["competitor"], result["benchmark"]["measured_tasks"], cycles


if __name__ == "__main__":
  unittest.main()
