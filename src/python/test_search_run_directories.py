import contextlib
import datetime
import io
import os
import re
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
    self.randomSeed = 0
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


class SearchRunDirectoryTest(unittest.TestCase):
  def test_run_id_format_and_output_root_normalization(self):
    with tempfile.TemporaryDirectory() as directory, change_directory(directory):
      run_directory = example.createRunDirectory("relative-results", now=datetime.datetime(2026, 8, 25, 14, 33, 41), randomSuffix=lambda: 4821)

      self.assertTrue(os.path.isabs(run_directory))
      self.assertEqual("2026-08-25-14-33-41-4821", os.path.basename(run_directory))
      self.assertRegex(os.path.basename(run_directory), r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{4}$")
      self.assertEqual(os.path.join(directory, "relative-results"), os.path.dirname(run_directory))

  def test_collision_retries_with_a_new_suffix(self):
    with tempfile.TemporaryDirectory() as output_root:
      timestamp = datetime.datetime(2026, 8, 25, 14, 33, 41)
      os.mkdir(os.path.join(output_root, "2026-08-25-14-33-41-4821"))
      suffixes = iter((4821, 4822))

      run_directory = example.createRunDirectory(output_root, now=timestamp, randomSuffix=lambda: next(suffixes))

      self.assertEqual("2026-08-25-14-33-41-4822", os.path.basename(run_directory))

  def test_example_creates_one_run_directory_and_shares_it(self):
    competition_module = sys.modules["competition"]
    runner = str(Path(example.__file__))
    with tempfile.TemporaryDirectory() as output_root:
      output = io.StringIO()
      with (
        mock.patch.object(competition_module, "Competition", RunnerCompetition, create=True),
        mock.patch.object(competition_module, "sourceData", return_value=object(), create=True),
        mock.patch.object(sys, "argv", [runner, "--source", "test", "--output-root", output_root]),
        contextlib.redirect_stdout(output),
      ):
        runpy.run_path(runner, run_name="__main__")

      children = list(Path(output_root).iterdir())
      self.assertEqual(1, len(children))
      self.assertEqual(str(children[0]), RunnerCompetition.instance.options["outputDir"])
      self.assertIn(f"Run directory: {children[0]}", output.getvalue())

  def test_competitor_iteration_and_legacy_paths(self):
    bench_util = load_bench_util()
    competitor = types.SimpleNamespace(name="baseline", competition=types.SimpleNamespace(jvmCount=2))

    legacy = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    legacy.outputDir = None
    self.assertEqual(
      (
        "%s/test.baseline.1" % bench_util.constants.LOGS_DIR,
        "%s/test.baseline.1.stdout" % bench_util.constants.LOGS_DIR,
        f"{bench_util.constants.LOGS_DIR}/bench-search-test-baseline-1.jfr",
        None,
      ),
      legacy.getSearchArtifactPaths(1, "test", competitor),
    )

    with tempfile.TemporaryDirectory() as run_directory:
      organized = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
      organized.outputDir = run_directory
      result, process, profile, perf_stat = organized.getSearchArtifactPaths(1, "test", competitor, create=True)
      iteration = os.path.join(run_directory, "baseline", "iteration-1")
      self.assertEqual(os.path.join(iteration, "result.log"), result)
      self.assertEqual(os.path.join(iteration, "process.log"), process)
      self.assertEqual(os.path.join(iteration, "profile.jfr"), profile)
      self.assertEqual(os.path.join(iteration, "perf.stat"), perf_stat)

  def test_only_search_artifact_command_arguments_change(self):
    bench_util = load_bench_util()
    legacy_command = run_search_and_capture_command(bench_util, None)
    with tempfile.TemporaryDirectory() as run_directory:
      organized_command = run_search_and_capture_command(bench_util, run_directory)

    def without_artifact_arguments(command):
      command = list(command)
      log_index = command.index("-log")
      del command[log_index : log_index + 2]
      return [argument for argument in command if not argument.startswith("JFR:")]

    self.assertEqual(without_artifact_arguments(legacy_command), without_artifact_arguments(organized_command))


@contextlib.contextmanager
def change_directory(path):
  previous = os.getcwd()
  os.chdir(path)
  try:
    yield
  finally:
    os.chdir(previous)


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


def run_search_and_capture_command(bench_util, output_directory):
  class Process:
    stdout = io.BytesIO()

    def wait(self):
      return 0

  index = types.SimpleNamespace(getPath=lambda: "index", facets=None)
  competition = types.SimpleNamespace(
    taskRepeatCount=2, taskCountPerCat=1, groupByCat=False, warmupTaskRepeatCount=None,
    perfControl=False, perfEvents=None, hardwareSummary=False,
  )
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

  with tempfile.TemporaryDirectory() as log_directory:
    if output_directory is None:
      logs_patch = mock.patch.object(bench_util.constants, "LOGS_DIR", log_directory)
    else:
      logs_patch = contextlib.nullcontext()
    with (
      logs_patch,
      mock.patch.object(bench_util, "PERF_EXE", None),
      mock.patch.object(bench_util, "getClassPath", return_value=[]),
      mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
      mock.patch.object(bench_util, "get_profiler_jvm_args", side_effect=lambda path, *args, **kwargs: f"JFR:{path}"),
      mock.patch.object(bench_util, "parseResults", return_value=([[]], None, 1000.0, 1.0)),
      mock.patch.object(bench_util.subprocess, "Popen", return_value=Process()) as popen,
      contextlib.redirect_stdout(io.StringIO()),
    ):
      runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
  return popen.call_args.args[0]


if __name__ == "__main__":
  unittest.main()
