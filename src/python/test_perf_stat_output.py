import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


class PerfStatOutputTest(unittest.TestCase):
  def test_organized_perf_uses_unique_parser_friendly_output(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      command, process_log, perf_stat = run_search(
        bench_util, run_directory, perf_executable="perf", perf_control=True,
        perf_events=("cycles", "ex_no_retire.load_not_complete"),
      )

      expected_prefix = [
        "perf", "stat", "-dd", "-x", ";", "--no-big-num", "-o", perf_stat,
        "-e", "cycles,ex_no_retire.load_not_complete", "--delay=-1", "--control=fifo:control,ack",
      ]
      self.assertEqual(expected_prefix, command[:len(expected_prefix)])
      self.assertEqual(
        os.path.join(run_directory, "baseline", "iteration-0", "perf.stat"),
        perf_stat,
      )
      self.assertEqual(
        os.path.join(run_directory, "baseline", "iteration-0", "process.log"),
        process_log,
      )
      self.assertIn(b"java diagnostic\n", Path(process_log).read_bytes())

  def test_formatting_does_not_change_java_or_perf_control_arguments(self):
    bench_util = load_bench_util()
    legacy_command, unused_process, legacy_perf_stat = run_search(
      bench_util, None, perf_executable="perf", perf_control=True,
      perf_events=("cycles", "instructions"),
    )
    with tempfile.TemporaryDirectory() as run_directory:
      organized_command, unused_process, organized_perf_stat = run_search(
        bench_util, run_directory, perf_executable="perf", perf_control=True,
        perf_events=("cycles", "instructions"),
      )

    self.assertIsNone(legacy_perf_stat)
    self.assertNotIn("-x", legacy_command)
    self.assertNotIn("-o", legacy_command)
    self.assertEqual(
      ["perf", "stat", "-dd", "-e", "cycles,instructions", "--delay=-1", "--control=fifo:control,ack"],
      legacy_command[:7],
    )
    def workload_arguments(command):
      arguments = list(command[command.index("java"):])
      arguments = [argument for argument in arguments if not argument.startswith("JFR:")]
      log_index = arguments.index("-log")
      del arguments[log_index : log_index + 2]
      return arguments

    self.assertEqual(workload_arguments(legacy_command), workload_arguments(organized_command))
    self.assertEqual(organized_perf_stat, organized_command[organized_command.index("-o") + 1])

  def test_competitors_and_iterations_have_distinct_perf_files(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
      runner.outputDir = run_directory
      paths = set()
      for competitor_name in ("baseline", "my_modified_version"):
        competitor = types.SimpleNamespace(name=competitor_name)
        for iteration in (0, 1):
          unused_result, unused_process, unused_profile, perf_stat = runner.getSearchArtifactPaths(iteration, "test", competitor)
          paths.add(perf_stat)

      self.assertEqual(4, len(paths))
      self.assertTrue(all(os.path.commonpath((run_directory, path)) == run_directory for path in paths))

  def test_perf_disabled_does_not_create_or_require_perf_stat(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      command, unused_process, perf_stat = run_search(bench_util, run_directory, perf_executable=None)

      self.assertEqual("java", command[0])
      self.assertFalse(os.path.exists(perf_stat))


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


def run_search(bench_util, output_directory, perf_executable, perf_control=False, perf_events=None):
  class Process:
    stdout = io.BytesIO(b"java diagnostic\n")

    def wait(self):
      return 0

  class ControlResources:
    controlPath = "control"
    ackPath = "ack"

    def __init__(self, unused_enabled):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *unused_args):
      pass

  exact = perf_control
  competition = types.SimpleNamespace(
    taskRepeatCount=2, taskCountPerCat=1, groupByCat=False,
    warmupTaskRepeatCount=0 if exact else None,
    measuredTaskRepeatCount=1 if exact else None,
    perfControl=perf_control, perfEvents=perf_events, hardwareSummary=False,
  )
  index = types.SimpleNamespace(getPath=lambda: "index", facets=None)
  competitor = types.SimpleNamespace(
    checkout="checkout", name="baseline", doSort=False, javaCommand="java", directory="MMapDirectory",
    index=index, analyzer="analyzer", tasksFile="tasks", numConcurrentQueries=1, competition=competition,
    searchConcurrency=0, similarity="similarity", commitPoint="multi", hiliteImpl="hilite", topN=10,
    testContext="", printHeap=False, pk=False, loadStoredFields=False, vectorDict=None, vectorFileName=None,
    vectorScale=None, exitable=False, pollute=False,
  )
  runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
  runner.verbose = False
  runner.outputDir = output_directory
  runner.compute_qps = mock.Mock(return_value=(1.0,))

  with tempfile.TemporaryDirectory() as legacy_logs:
    logs_patch = mock.patch.object(bench_util.constants, "LOGS_DIR", legacy_logs) if output_directory is None else contextlib.nullcontext()
    with (
      logs_patch,
      mock.patch.object(bench_util, "PERF_EXE", perf_executable),
      mock.patch.object(bench_util, "PerfControlResources", ControlResources),
      mock.patch.object(bench_util, "getClassPath", return_value=[]),
      mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
      mock.patch.object(bench_util, "get_profiler_jvm_args", side_effect=lambda path, *args, **kwargs: f"JFR:{path}"),
      mock.patch.object(bench_util, "parseResults", return_value=([[]], None, 1000.0, 1.0)),
      mock.patch.object(bench_util.subprocess, "Popen", return_value=Process()) as popen,
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)

    process_log = runner.getSearchArtifactPaths(0, "test", competitor)[1]
    perf_stat = runner.getSearchArtifactPaths(0, "test", competitor)[3]
    return popen.call_args.args[0], process_log, perf_stat


if __name__ == "__main__":
  unittest.main()
