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


class RunnerCompetition:
  instance = None

  def __init__(self, **kwargs):
    RunnerCompetition.instance = self
    self.options = kwargs
    self.randomSeed = 0 if kwargs.get("randomSeed") is None else kwargs["randomSeed"]
    self.indexOptions = []
    self.competitors = []
    self.benchmarkCalls = 0
    self.skipIndexCalls = 0
    self.skipSearchCalls = 0

  def skipIndex(self):
    self.skipIndexCalls += 1

  def skipSearch(self):
    self.skipSearchCalls += 1

  def addTaskPattern(self, unused_pattern):
    pass

  def setRequestedTaskCategories(self, unused_categories):
    pass

  def newIndex(self, *unused_args, **kwargs):
    self.indexOptions.append(kwargs)
    return types.SimpleNamespace(getPath=lambda: kwargs.get("indexPath") or "generated-index")

  def competitor(self, name, checkout, **kwargs):
    self.competitors.append((name, checkout, kwargs))

  def benchmark(self, unused_id):
    self.benchmarkCalls += 1


class IndexThreadsTest(unittest.TestCase):
  def run_runner(self, *arguments):
    competition_module = sys.modules["competition"]
    runner_path = str(Path(example.__file__))
    argv = [runner_path, "--source", "test", *arguments]
    stdout = io.StringIO()
    with (
      mock.patch.object(competition_module, "Competition", RunnerCompetition, create=True),
      mock.patch.object(competition_module, "sourceData", return_value=object(), create=True),
      mock.patch.object(sys, "argv", argv),
      contextlib.redirect_stdout(stdout),
    ):
      runpy.run_path(runner_path, run_name="__main__")
    RunnerCompetition.instance.consoleOutput = stdout.getvalue()
    return RunnerCompetition.instance

  def assert_cli_rejected(self, value):
    runner_path = str(Path(example.__file__))
    stderr = io.StringIO()
    with (
      mock.patch.object(sys, "argv", [runner_path, "--source", "test", "--index-threads", str(value)]),
      contextlib.redirect_stderr(stderr),
      self.assertRaises(SystemExit) as raised,
    ):
      runpy.run_path(runner_path, run_name="__main__")
    self.assertEqual(2, raised.exception.code)
    self.assertIn("argument --index-threads: must be at least 1", stderr.getvalue())

  def test_default_is_one(self):
    comp = self.run_runner()
    self.assertEqual(1, comp.indexOptions[0]["numThreads"])

  def test_explicit_value_reaches_index(self):
    comp = self.run_runner("--index-threads", "8")
    self.assertEqual(8, comp.indexOptions[0]["numThreads"])

  def test_build_configuration_prints_resolved_value(self):
    comp = self.run_runner("--mode", "build", "--index-threads", "16")
    self.assertIn("index threads: 16", comp.consoleOutput)

  def test_zero_and_negative_are_rejected(self):
    for value in (0, -1):
      self.assert_cli_rejected(value)

  def test_search_and_query_concurrency_are_unchanged(self):
    comp = self.run_runner(
      "--index-threads", "8", "--query-concurrency", "3", "--search-concurrency", "2"
    )
    for unused_name, unused_checkout, options in comp.competitors:
      self.assertEqual(3, options["numConcurrentQueries"])
      self.assertEqual(2, options["searchConcurrency"])

  def test_search_execution_and_index_path_are_unchanged(self):
    with tempfile.TemporaryDirectory() as index_path:
      comp = self.run_runner(
        "--mode", "search", "--index-path", index_path, "--index-threads", "8"
      )
    self.assertEqual(1, comp.skipIndexCalls)
    self.assertEqual(0, comp.skipSearchCalls)
    self.assertEqual(1, comp.benchmarkCalls)
    self.assertEqual(os.path.abspath(index_path), comp.indexOptions[0]["indexPath"])

  def test_sixteen_reaches_indexer_command(self):
    bench_util = self.load_bench_util()
    captured = []

    def fake_run(command, log_file, **unused_kwargs):
      captured.append(command)
      Path(log_file).write_bytes(b"")

    index = self.fake_index(16)
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    runner.verbose = False
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as directory:
      try:
        with (
        mock.patch.object(bench_util.constants, "LOGS_DIR", directory),
        mock.patch.object(bench_util, "checkoutToBenchPath", return_value=directory),
        mock.patch.object(bench_util, "checkoutToPath", return_value=directory),
        mock.patch.object(bench_util, "getClassPath", return_value=[]),
        mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
        mock.patch.object(bench_util, "get_profiler_jvm_args", return_value=""),
        mock.patch.object(bench_util, "profilerOutput", return_value=None),
        mock.patch.object(bench_util, "run", side_effect=fake_run),
        contextlib.redirect_stdout(io.StringIO()),
        ):
          runner.makeIndex("test", index)
      finally:
        os.chdir(original_cwd)

    command = captured[0]
    position = command.index("-threadCount")
    self.assertEqual(["-threadCount", "16"], command[position : position + 2])

  def test_shared_index_is_built_once(self):
    bench_util = self.load_bench_util()
    with mock.patch.dict(
      sys.modules,
      {"benchUtil": bench_util, "common": bench_util.common, "constants": bench_util.constants},
    ):
      import searchBench

    class SharedIndex:
      def getPath(self):
        return "index"

    shared_index = SharedIndex()
    competition = types.SimpleNamespace(
      hardwareSummary=False, outputDir=None, verbose=False, jvmCount=20, profile="none"
    )
    base = types.SimpleNamespace(
      competition=competition, index=shared_index, checkout="checkout", commitPoint="multi"
    )
    challenger = types.SimpleNamespace(
      competition=competition, index=shared_index, checkout="checkout", commitPoint="multi"
    )

    class FakeRunAlgs:
      instance = None

      def __init__(self, *unused_args, **unused_kwargs):
        FakeRunAlgs.instance = self
        self.makeIndex = mock.Mock()

      def compile(self, unused_competitor):
        pass

    with (
      mock.patch.object(searchBench.benchUtil, "RunAlgs", FakeRunAlgs),
      mock.patch.object(searchBench.benchUtil, "getSegmentCount", return_value=1),
      mock.patch.object(sys, "argv", ["test"]),
      contextlib.redirect_stdout(io.StringIO()),
    ):
      searchBench.run(
        "test", base, challenger, search=False, index=True, randomSeed=0, skipReport=True
      )

    FakeRunAlgs.instance.makeIndex.assert_called_once()

  @staticmethod
  def load_bench_util():
    pwd = types.ModuleType("pwd")
    pwd.getpwuid = lambda unused_uid: types.SimpleNamespace(pw_name="test")
    localconstants = types.ModuleType("localconstants")
    localconstants.BASE_DIR = tempfile.gettempdir()
    with mock.patch.dict(sys.modules, {"localconstants": localconstants, "pwd": pwd}):
      import benchUtil
    return benchUtil

  @staticmethod
  def fake_index(num_threads):
    return types.SimpleNamespace(
      getPath=lambda: "new-index",
      doUpdate=False,
      checkout="checkout",
      javaCommand="java",
      getName=lambda: "index-name",
      directory="MMapDirectory",
      analyzer="StandardAnalyzer",
      lineDocSource="docs",
      numDocs=10,
      numThreads=num_threads,
      maxConcurrentMerges=None,
      addDVFields=True,
      addDVSkippers=False,
      useCMS=True,
      vectorFile=None,
      optimize=False,
      verbose=False,
      ramBufferMB=-1,
      maxBufferedDocs=10,
      postingsFormat="Lucene104",
      doDeletions=False,
      printDPS=False,
      waitForMerges=True,
      mergePolicy="TieredMergePolicy",
      facets=None,
      idFieldPostingsFormat="Lucene104",
      grouping=True,
      useCFS=False,
      bodyTermVectors=False,
      bodyPostingsOffsets=False,
      bodyStoredFields=False,
      waitForCommit=True,
      ioThrottle=None,
      indexSort=None,
      rearrange=0,
      hnswThreadsPerMerge=1,
      hnswThreadPoolCount=1,
      quantizeKNNGraph=False,
    )


if __name__ == "__main__":
  unittest.main()
