import contextlib
import io
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.modules.setdefault("competition", types.ModuleType("competition"))

import example
from test_exact_workload_phases import RunnerCompetition


class PerfControlTest(unittest.TestCase):
  def exact_arguments(self):
    return ("--warmup-repetitions", "1", "--measured-repetitions", "2", "--tasks-per-category", "1")

  def run_runner(self, *arguments):
    competition_module = sys.modules["competition"]
    runner_path = str(Path(example.__file__))
    with (
      mock.patch.object(competition_module, "Competition", RunnerCompetition, create=True),
      mock.patch.object(competition_module, "sourceData", return_value=object(), create=True),
      mock.patch.object(sys, "argv", [runner_path, "--source", "test", *arguments]),
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runpy.run_path(runner_path, run_name="__main__")
    return RunnerCompetition.instance

  def assert_cli_rejected(self, arguments, message):
    runner_path = str(Path(example.__file__))
    stderr = io.StringIO()
    with (
      mock.patch.object(sys, "argv", [runner_path, "--source", "test", *arguments]),
      contextlib.redirect_stderr(stderr),
      self.assertRaises(SystemExit) as raised,
    ):
      runpy.run_path(runner_path, run_name="__main__")
    self.assertEqual(2, raised.exception.code)
    self.assertIn(message, stderr.getvalue())

  def test_perf_control_requires_exact_phases(self):
    self.assert_cli_rejected(("--perf-control",), "requires the complete exact workload phase configuration")

  def test_build_mode_rejects_perf_control(self):
    self.assert_cli_rejected(("--mode", "build", "--perf-control", *self.exact_arguments()), "applies only when search is enabled")

  def test_perf_control_reaches_competition(self):
    competition = self.run_runner(*self.exact_arguments(), "--perf-control")
    self.assertTrue(competition.options["perfControl"])

  def test_command_variants_and_endpoint_cleanup(self):
    bench_util = self.load_bench_util()
    legacy = self.run_command(bench_util, exact=False, controlled=False)
    exact = self.run_command(bench_util, exact=True, controlled=False)
    controlled = self.run_command(bench_util, exact=True, controlled=True)

    for command in (legacy, exact):
      self.assertNotIn("--delay=-1", command)
      self.assertFalse(any(argument.startswith("--control=") for argument in command))
      self.assertNotIn("-perfControlPath", command)
      self.assertNotIn("-perfAckPath", command)

    self.assertIn("-taskRepeatCount", legacy)
    self.assertIn("-warmupTaskRepeatCount", exact)
    self.assertIn("--delay=-1", controlled)
    control_argument = next(argument for argument in controlled if argument.startswith("--control=fifo:"))
    control_path, ack_path = control_argument.removeprefix("--control=fifo:").split(",")
    self.assertEqual(control_path, controlled[controlled.index("-perfControlPath") + 1])
    self.assertEqual(ack_path, controlled[controlled.index("-perfAckPath") + 1])
    self.assertFalse(os.path.exists(os.path.dirname(control_path)))

  def test_java_boundary_order(self):
    source = (Path(__file__).parents[2] / "src/main/perf/SearchPerfTest.java").read_text(encoding="utf-8")
    positions = [
      source.index("---- MEASURED PHASE READY ----"),
      source.index("perfControl.enableAndWaitForAck();"),
      source.index("measuredStartNanos = System.nanoTime();"),
      source.index("measuredThreads.start();"),
      source.index("measuredThreads.finish();"),
      source.index("measuredEndNanos = System.nanoTime();"),
      source.index("perfControl.disableAndWaitForAck();"),
      source.index("---- MEASURED PHASE COMPLETE ----"),
    ]
    self.assertEqual(positions, sorted(positions))

  def run_command(self, bench_util, exact, controlled):
    class Process:
      stdout = io.BytesIO()

      def wait(self):
        return 0

    competition = types.SimpleNamespace(
      taskRepeatCount=20,
      taskCountPerCat=1,
      groupByCat=False,
      warmupTaskRepeatCount=1 if exact else None,
      measuredTaskRepeatCount=2 if exact else None,
      perfControl=controlled,
    )
    competitor = types.SimpleNamespace(
      checkout="checkout", name="candidate", doSort=False, javaCommand="java", directory="MMapDirectory",
      index=types.SimpleNamespace(getPath=lambda: "index", facets=None), analyzer="analyzer", tasksFile="tasks",
      numConcurrentQueries=1, competition=competition, searchConcurrency=0, similarity="similarity", commitPoint="multi",
      hiliteImpl="hilite", topN=10, testContext="", printHeap=False, pk=False, loadStoredFields=False,
      vectorDict=None, vectorFileName=None, vectorScale=None, exitable=False, pollute=False,
    )
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    runner.compute_qps = mock.Mock(return_value=(0.0,))

    def make_fifo(path):
      Path(path).touch()

    with (
      tempfile.TemporaryDirectory() as directory,
      mock.patch.object(bench_util.constants, "LOGS_DIR", directory),
      mock.patch.object(bench_util, "PERF_EXE", "/usr/bin/perf"),
      mock.patch.object(bench_util, "osName", "linux"),
      mock.patch.object(bench_util.os, "mkfifo", side_effect=make_fifo, create=True),
      mock.patch.object(bench_util, "getClassPath", return_value=[]),
      mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
      mock.patch.object(bench_util, "get_profiler_jvm_args", return_value=""),
      mock.patch.object(bench_util, "parseResults", return_value=([], None, 1, 0)),
      mock.patch.object(bench_util.subprocess, "Popen", return_value=Process()) as popen,
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
    return popen.call_args.args[0]

  @staticmethod
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


if __name__ == "__main__":
  unittest.main()
