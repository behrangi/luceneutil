import contextlib
import io
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


class RunnerCompetition:
  instance = None

  def __init__(self, **kwargs):
    RunnerCompetition.instance = self
    self.options = kwargs
    self.competitors = []
    self.patterns = []

  def skipIndex(self):
    pass

  def skipSearch(self):
    pass

  def addTaskPattern(self, pattern):
    self.patterns.append(pattern)

  def setRequestedTaskCategories(self, categories):
    self.categories = tuple(categories)

  def newIndex(self, *unused_args, **unused_kwargs):
    return object()

  def competitor(self, name, checkout, **kwargs):
    self.competitors.append((name, checkout, kwargs))

  def benchmark(self, unused_id):
    pass


class ConcurrencyControlsTest(unittest.TestCase):
  def run_runner(self, *arguments):
    competition_module = sys.modules["competition"]
    runner_path = str(Path(example.__file__))
    argv = [runner_path, "--source", "test", *arguments]
    with (
      mock.patch.object(competition_module, "Competition", RunnerCompetition, create=True),
      mock.patch.object(competition_module, "sourceData", return_value=object(), create=True),
      mock.patch.object(sys, "argv", argv),
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runpy.run_path(runner_path, run_name="__main__")
    return RunnerCompetition.instance

  def assert_cli_rejected(self, option, value, message):
    runner_path = str(Path(example.__file__))
    stderr = io.StringIO()
    with (
      mock.patch.object(sys, "argv", [runner_path, "--source", "test", option, str(value)]),
      contextlib.redirect_stderr(stderr),
      self.assertRaises(SystemExit) as raised,
    ):
      runpy.run_path(runner_path, run_name="__main__")
    self.assertEqual(2, raised.exception.code)
    self.assertIn(message, stderr.getvalue())

  def test_query_concurrency_accepts_one_and_larger_values(self):
    for value in (1, 8):
      competition = self.run_runner("--query-concurrency", str(value))
      for unused_name, unused_checkout, options in competition.competitors:
        self.assertEqual(value, options["numConcurrentQueries"])

  def test_query_concurrency_cli_rejects_zero(self):
    self.assert_cli_rejected("--query-concurrency", 0, "argument --query-concurrency: must be at least 1")

  def test_query_concurrency_cli_rejects_negative_value(self):
    self.assert_cli_rejected("--query-concurrency", -1, "argument --query-concurrency: must be at least 1")

  def test_search_concurrency_accepts_supported_values(self):
    for value in (-1, 0, 4):
      competition = self.run_runner("--search-concurrency", str(value))
      for unused_name, unused_checkout, options in competition.competitors:
        self.assertEqual(value, options["searchConcurrency"])

  def test_search_concurrency_cli_rejects_value_below_minus_one(self):
    self.assert_cli_rejected("--search-concurrency", -2, "must be -1 or greater")

  def test_legacy_search_concurrency_alias(self):
    competition = self.run_runner("--searchConcurrency", "3")
    for unused_name, unused_checkout, options in competition.competitors:
      self.assertEqual(3, options["searchConcurrency"])

  def test_omission_preserves_historical_defaults(self):
    competition = self.run_runner()
    for unused_name, unused_checkout, options in competition.competitors:
      self.assertNotIn("numConcurrentQueries", options)
      self.assertEqual(-1, options["searchConcurrency"])

  def test_query_selection_is_unchanged(self):
    competition = self.run_runner("--queries", "HighTerm", "--query-concurrency", "2")
    self.assertEqual(["^HighTerm$"], competition.patterns)
    for unused_name, unused_checkout, options in competition.competitors:
      self.assertFalse(options["pk"])
      self.assertEqual(2, options["numConcurrentQueries"])

  def test_values_reach_search_perf_test_arguments(self):
    pwd = types.ModuleType("pwd")
    pwd.getpwuid = lambda unused_uid: types.SimpleNamespace(pw_name="test")
    localconstants = types.ModuleType("localconstants")
    localconstants.BASE_DIR = tempfile.gettempdir()
    sys.modules.pop("benchUtil", None)
    sys.modules.pop("constants", None)
    with mock.patch.dict(sys.modules, {"localconstants": localconstants, "pwd": pwd}):
      import benchUtil

    class Process:
      def __init__(self):
        self.stdout = io.BytesIO()

      def wait(self):
        return 0

    index = types.SimpleNamespace(getPath=lambda: "index", facets=None)
    competition = types.SimpleNamespace(taskRepeatCount=20, taskCountPerCat=1, groupByCat=False)
    competitor = types.SimpleNamespace(
      checkout="checkout",
      name="candidate",
      doSort=False,
      javaCommand="java",
      directory="MMapDirectory",
      index=index,
      analyzer="analyzer",
      tasksFile="tasks",
      numConcurrentQueries=7,
      competition=competition,
      searchConcurrency=3,
      similarity="similarity",
      commitPoint="multi",
      hiliteImpl="hilite",
      topN=10,
      testContext="",
      printHeap=False,
      pk=False,
      loadStoredFields=False,
      vectorDict=None,
      vectorFileName=None,
      vectorScale=None,
      exitable=False,
      pollute=False,
    )
    runner = benchUtil.RunAlgs.__new__(benchUtil.RunAlgs)
    runner.compute_qps = mock.Mock(return_value=(0.0,))

    with (
      tempfile.TemporaryDirectory() as directory,
      mock.patch.object(benchUtil.constants, "LOGS_DIR", directory),
      mock.patch.object(benchUtil, "PERF_EXE", None),
      mock.patch.object(benchUtil, "getClassPath", return_value=[]),
      mock.patch.object(benchUtil, "classPathToString", return_value="classpath"),
      mock.patch.object(benchUtil, "get_profiler_jvm_args", return_value=""),
      mock.patch.object(benchUtil, "parseResults", return_value=([], None, 0, 0)),
      mock.patch.object(benchUtil.subprocess, "Popen", return_value=Process()) as popen,
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)

    command = popen.call_args.args[0]
    query_index = command.index("-numConcurrentQueries")
    search_index = command.index("-searchConcurrency")
    self.assertEqual(["-numConcurrentQueries", "7"], command[query_index : query_index + 2])
    self.assertEqual(["-searchConcurrency", "3"], command[search_index : search_index + 2])


if __name__ == "__main__":
  unittest.main()
