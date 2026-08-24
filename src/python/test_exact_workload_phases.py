import contextlib
import io
import runpy
import sys
import tempfile
import types
import unittest
import warnings
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


class ExactWorkloadPhasesTest(unittest.TestCase):
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

  def exact_arguments(self, warmup=3, measured=5, tasks=2):
    return (
      "--warmup-repetitions",
      str(warmup),
      "--measured-repetitions",
      str(measured),
      "--tasks-per-category",
      str(tasks),
    )

  def test_exact_values_reach_execution_configuration(self):
    competition = self.run_runner(*self.exact_arguments())

    self.assertEqual(3, competition.options["warmupTaskRepeatCount"])
    self.assertEqual(5, competition.options["measuredTaskRepeatCount"])
    self.assertEqual(2, competition.options["taskCountPerCat"])

  def test_exact_values_reach_search_perf_test_arguments(self):
    bench_util = self.load_bench_util()

    class Process:
      def __init__(self):
        self.stdout = io.BytesIO()

      def wait(self):
        return 0

    index = types.SimpleNamespace(getPath=lambda: "index", facets=None)
    competition = types.SimpleNamespace(
      taskRepeatCount=20,
      taskCountPerCat=2,
      groupByCat=False,
      warmupTaskRepeatCount=3,
      measuredTaskRepeatCount=5,
    )
    competitor = types.SimpleNamespace(
      checkout="checkout",
      name="candidate",
      doSort=False,
      javaCommand="java",
      directory="MMapDirectory",
      index=index,
      analyzer="analyzer",
      tasksFile="tasks",
      numConcurrentQueries=1,
      competition=competition,
      searchConcurrency=0,
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
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    runner.compute_qps = mock.Mock(return_value=(0.0,))

    with (
      tempfile.TemporaryDirectory() as directory,
      mock.patch.object(bench_util.constants, "LOGS_DIR", directory),
      mock.patch.object(bench_util, "PERF_EXE", None),
      mock.patch.object(bench_util, "getClassPath", return_value=[]),
      mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
      mock.patch.object(bench_util, "get_profiler_jvm_args", return_value=""),
      mock.patch.object(bench_util, "parseResults", return_value=([], None, 1, 0)),
      mock.patch.object(bench_util.subprocess, "Popen", return_value=Process()) as popen,
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)

    command = popen.call_args.args[0]
    warmup_index = command.index("-warmupTaskRepeatCount")
    measured_index = command.index("-measuredTaskRepeatCount")
    tasks_index = command.index("-tasksPerCat")
    self.assertEqual(["-warmupTaskRepeatCount", "3"], command[warmup_index : warmup_index + 2])
    self.assertEqual(["-measuredTaskRepeatCount", "5"], command[measured_index : measured_index + 2])
    self.assertEqual(["-tasksPerCat", "2"], command[tasks_index : tasks_index + 2])
    self.assertNotIn("-taskRepeatCount", command)

  def test_zero_one_and_larger_warmup_values(self):
    for value in (0, 1, 4):
      competition = self.run_runner(*self.exact_arguments(warmup=value))
      self.assertEqual(value, competition.options["warmupTaskRepeatCount"])

  def test_one_and_larger_measured_values(self):
    for value in (1, 6):
      competition = self.run_runner(*self.exact_arguments(measured=value))
      self.assertEqual(value, competition.options["measuredTaskRepeatCount"])

  def test_one_and_larger_tasks_per_category_values(self):
    for value in (1, 7):
      competition = self.run_runner(*self.exact_arguments(tasks=value))
      self.assertEqual(value, competition.options["taskCountPerCat"])

  def test_invalid_phase_values_are_rejected_by_cli(self):
    cases = (
      (("--warmup-repetitions", "-1"), "must be at least 0"),
      (("--measured-repetitions", "0"), "must be at least 1"),
      (("--measured-repetitions", "-1"), "must be at least 1"),
      (("--tasks-per-category", "0"), "must be at least 1"),
      (("--tasks-per-category", "-1"), "must be at least 1"),
    )
    for arguments, message in cases:
      self.assert_cli_rejected(arguments, message)

  def test_partial_exact_configuration_is_rejected(self):
    self.assert_cli_rejected(("--warmup-repetitions", "1"), "exact workload phases require")

  def test_legacy_warmups_cannot_be_mixed_with_exact_configuration(self):
    self.assert_cli_rejected(("--warmups", "20", *self.exact_arguments()), "--warmups cannot be combined")

  def test_build_only_exact_configuration_is_rejected(self):
    self.assert_cli_rejected(("--mode", "build", *self.exact_arguments()), "apply only when search is enabled")

  def test_legacy_invocation_preserves_task_repeat_count(self):
    competition = self.run_runner()

    self.assertEqual(20, competition.options["taskRepeatCount"])
    self.assertNotIn("warmupTaskRepeatCount", competition.options)
    self.assertNotIn("measuredTaskRepeatCount", competition.options)

  def test_query_and_concurrency_configuration_is_shared(self):
    for queries, expected_pk in (("HighTerm", False), ("PKLookup", True), ("HighTerm,PKLookup", True)):
      competition = self.run_runner(
        *self.exact_arguments(),
        "--queries",
        queries,
        "--query-concurrency",
        "3",
        "--search-concurrency",
        "2",
      )
      self.assertEqual(2, len(competition.competitors))
      for unused_name, unused_checkout, options in competition.competitors:
        self.assertEqual(3, options["numConcurrentQueries"])
        self.assertEqual(2, options["searchConcurrency"])
        self.assertEqual(expected_pk, options["pk"])

  def test_java_measured_phase_markers_surround_execution(self):
    search = (Path(__file__).parents[2] / "src/main/perf/SearchPerfTest.java").read_text(encoding="utf-8")
    conditional_warmup = search.index("if (warmupTaskRepeatCount > 0)")
    measured_construction = search.index("exactWorkload.newTaskSource(measuredTaskRepeatCount")
    measured_ready = search.index("---- MEASURED PHASE READY ----")
    measured_start = search.index("measuredThreads.start();")
    measured_finish = search.index("measuredThreads.finish();")
    measured_complete = search.index("---- MEASURED PHASE COMPLETE ----")

    self.assertLess(conditional_warmup, measured_construction)
    self.assertLess(measured_construction, measured_ready)
    self.assertLess(measured_ready, measured_start)
    self.assertLess(measured_start, measured_finish)
    self.assertLess(measured_finish, measured_complete)

  def test_exact_reporting_uses_all_tasks_and_measured_duration(self):
    bench_util = self.load_bench_util()
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    tasks = [types.SimpleNamespace(startMsec=0.0, msec=1.0) for unused in range(10)]

    self.assertEqual([5.0], runner.compute_qps([tasks], 2000.0, exactPhases=True))

  def test_legacy_qps_still_discards_initial_five_seconds(self):
    bench_util = self.load_bench_util()
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    tasks = [types.SimpleNamespace(startMsec=float(second * 1000), msec=1.0) for second in range(8)]

    self.assertEqual([1.0], runner.compute_qps([tasks], 8000.0, exactPhases=False))

  def test_exact_mode_does_not_apply_warm_skip(self):
    bench_util = self.load_bench_util()

    class Result:
      msec = 7.0

    task = object()
    results = [{("HighTerm",): ([task], {task: [Result()]})}]
    exact_ms, unused_hits = bench_util.agg(results, ("HighTerm",), "exact", False, warmSkip=0)
    self.assertEqual([7.0], exact_ms)
    with self.assertRaisesRegex(RuntimeError, "only 1 tasks"):
      bench_util.agg(results, ("HighTerm",), "legacy", False)

  def test_parser_prefers_explicit_measured_phase_elapsed(self):
    bench_util = self.load_bench_util()
    with tempfile.TemporaryDirectory() as directory:
      log_file = Path(directory) / "result.log"
      log_file.write_text("Start of tasks winddown: 10.0 msec\nMeasured phase elapsed: 25.0 msec\n", encoding="utf-8")
      with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        unused_results, unused_heap, elapsed, unused_cpu = bench_util.parseResults([str(log_file)])
    self.assertEqual(25.0, elapsed)

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
