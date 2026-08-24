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


class SummaryCompetition:
  instance = None

  def __init__(self, **kwargs):
    SummaryCompetition.instance = self
    self.options = kwargs
    self.randomSeed = 0 if kwargs.get("randomSeed") is None else kwargs["randomSeed"]
    self.competitors = []

  def skipIndex(self):
    pass

  def skipSearch(self):
    pass

  def addTaskPattern(self, unused_pattern):
    pass

  def setRequestedTaskCategories(self, unused_categories):
    pass

  def newIndex(self, *unused_args, **unused_kwargs):
    return object()

  def competitor(self, name, checkout, **kwargs):
    self.competitors.append((name, checkout, kwargs))

  def benchmark(self, unused_id):
    pass


class HardwareSummaryTest(unittest.TestCase):
  EXACT = ("--warmup-repetitions", "0", "--measured-repetitions", "5", "--tasks-per-category", "2")

  def run_runner(self, *args):
    module = sys.modules["competition"]
    runner = str(Path(example.__file__))
    with (
      mock.patch.object(module, "Competition", SummaryCompetition, create=True),
      mock.patch.object(module, "sourceData", return_value=object(), create=True),
      mock.patch.object(sys, "argv", [runner, "--source", "test", *args]),
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runpy.run_path(runner, run_name="__main__")
    return SummaryCompetition.instance

  def test_hardware_summary_requires_exact_phases(self):
    runner = str(Path(example.__file__))
    stderr = io.StringIO()
    with (
      mock.patch.object(sys, "argv", [runner, "--source", "test", "--hardware-summary"]),
      contextlib.redirect_stderr(stderr),
      self.assertRaises(SystemExit),
    ):
      runpy.run_path(runner, run_name="__main__")
    self.assertIn("requires the complete exact workload phase configuration", stderr.getvalue())

  def test_hardware_summary_rejects_build_only(self):
    runner = str(Path(example.__file__))
    stderr = io.StringIO()
    with (
      mock.patch.object(sys, "argv", [runner, "--source", "test", "--mode", "build", *self.EXACT, "--hardware-summary"]),
      contextlib.redirect_stderr(stderr),
      self.assertRaises(SystemExit),
    ):
      runpy.run_path(runner, run_name="__main__")
    self.assertIn("apply only when search is enabled", stderr.getvalue())

  def test_regular_and_pk_summary_configuration(self):
    for queries, expected_pk in (("HighTerm", False), ("PKLookup", True)):
      comp = self.run_runner(*self.EXACT, "--hardware-summary", "--queries", queries)
      self.assertTrue(comp.options["hardwareSummary"])
      self.assertTrue(all(options["pk"] is expected_pk for unused_name, unused_checkout, options in comp.competitors))

  def test_summary_parser_reads_only_scalars(self):
    bench_util = self.load_bench_util()
    with tempfile.TemporaryDirectory() as directory:
      log = Path(directory) / "summary.log"
      log.write_text(
        "Hardware summary measured tasks: 10\n"
        "Hardware summary measured elapsed msec: 2000.0\n"
        "Hardware summary QPS: 5.0\n"
        "Average CPU cores used: 3.5\n",
        encoding="utf-8",
      )
      self.assertEqual(
        {"measuredTasks": 10, "measuredElapsedMS": 2000.0, "qps": 5.0, "avgCPUCores": 3.5},
        bench_util.parseHardwareSummary(log),
      )

  def test_summary_execution_skips_detailed_result_parser(self):
    bench_util = self.load_bench_util()

    class Process:
      stdout = io.BytesIO(b"---- MEASURED PHASE READY ----\n---- MEASURED PHASE COMPLETE ----\n")

      def wait(self):
        return 0

    competition = types.SimpleNamespace(
      taskRepeatCount=20, taskCountPerCat=2, groupByCat=False, warmupTaskRepeatCount=0,
      measuredTaskRepeatCount=5, perfControl=False, perfEvents=None, hardwareSummary=True,
    )
    index = types.SimpleNamespace(getPath=lambda: "index", facets=None)
    competitor = types.SimpleNamespace(
      checkout="checkout", name="candidate", doSort=False, javaCommand="java", directory="MMapDirectory",
      index=index, analyzer="analyzer", tasksFile="tasks", numConcurrentQueries=1, competition=competition,
      searchConcurrency=0, similarity="similarity", commitPoint="multi", hiliteImpl="hilite", topN=10,
      testContext="", printHeap=False, pk=False, loadStoredFields=False, vectorDict=None, vectorFileName=None,
      vectorScale=None, exitable=False, pollute=False,
    )
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    runner.verbose = False

    with tempfile.TemporaryDirectory() as directory:
      result = Path(directory) / "test.candidate.0"
      def fake_popen(command, **unused_kwargs):
        result.write_text(
          "Hardware summary measured tasks: 10\nHardware summary measured elapsed msec: 2000.0\n"
          "Hardware summary QPS: 5.0\nAverage CPU cores used: 3.5\n",
          encoding="utf-8",
        )
        return Process()
      output = io.StringIO()
      with (
        mock.patch.object(bench_util.constants, "LOGS_DIR", directory),
        mock.patch.object(bench_util, "PERF_EXE", None),
        mock.patch.object(bench_util, "getClassPath", return_value=[]),
        mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
        mock.patch.object(bench_util, "get_profiler_jvm_args", return_value=""),
        mock.patch.object(bench_util, "parseResults") as parse_results,
        mock.patch.object(bench_util.subprocess, "Popen", side_effect=fake_popen) as popen,
        contextlib.redirect_stdout(output),
      ):
        runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
      parse_results.assert_not_called()
      command = popen.call_args.args[0]
      self.assertIn("-hardwareSummary", command)
      self.assertIn("measured tasks: 10", output.getvalue())
      self.assertIn("QPS: 5.0", output.getvalue())

  def test_search_orchestration_skips_comparison_report_and_chart_path(self):
    bench_util = self.load_bench_util()
    sys.modules.pop("searchBench", None)
    common = types.SimpleNamespace(osName=bench_util.osName)
    with mock.patch.dict(sys.modules, {"benchUtil": bench_util, "constants": bench_util.constants, "common": common}):
      import searchBench

    competition = types.SimpleNamespace(
      verbose=False, hardwareSummary=True, jvmCount=1, warmupTaskRepeatCount=0,
    )
    index = object()
    base = mock.Mock(name="baselineCompetitor", name_attr="baseline")
    base.name = "baseline"
    base.competition = competition
    base.tasksFile = "tasks"
    base.index = index
    candidate = mock.Mock(name="candidateCompetitor")
    candidate.name = "candidate"
    candidate.competition = competition
    candidate.tasksFile = "tasks"
    candidate.index = index
    fake_runner = mock.Mock()
    fake_runner.getSearchLogFiles.return_value = []
    fake_runner.runSimpleSearchBench.return_value = "summary.log"

    with (
      mock.patch.object(searchBench.benchUtil, "RunAlgs", return_value=fake_runner),
      mock.patch.object(searchBench, "validateTaskCategories"),
      mock.patch.object(searchBench.os.path, "exists", return_value=False),
      mock.patch.object(sys, "argv", ["test", "-noc"]),
      contextlib.redirect_stdout(io.StringIO()),
    ):
      searchBench.run(
        "test", base, candidate, search=True, index=False, randomSeed=1,
        taskPatterns=(None, None), requestedTaskCategories=None,
      )

    fake_runner.simpleReport.assert_not_called()

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
