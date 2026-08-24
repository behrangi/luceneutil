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
from test_exact_workload_phases import RunnerCompetition


class VerbosityControlsTest(unittest.TestCase):
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

  def test_default_and_explicit_verbose_configuration(self):
    self.assertFalse(self.run_runner().options["verbose"])
    self.assertTrue(self.run_runner("--verbose").options["verbose"])

  def test_concise_and_verbose_commands_are_identical(self):
    with tempfile.TemporaryDirectory() as directory:
      concise_command, concise_output, concise_log = self.run_search(verbose=False, directory=directory)
      verbose_command, verbose_output, unused_verbose_log = self.run_search(verbose=True, directory=directory)

    self.assertEqual(concise_command, verbose_command)
    self.assertNotIn("      run:", concise_output)
    self.assertIn("      run:", verbose_output)
    self.assertIn("COMMAND: ", concise_log)
    self.assertIn("warmup complete", concise_output)
    self.assertIn("measured phase ready", concise_output)
    self.assertNotIn("measured phase started", concise_output)
    self.assertIn("measured phase complete", concise_output)
    self.assertIn("measured elapsed: 1.234 s", concise_output)
    self.assertIn("QPS: 12345.6", concise_output)
    self.assertIn("CPU cores used: 3.9", concise_output)
    self.assertIn("log:", concise_output)

  def test_legacy_concise_output_does_not_claim_measured_elapsed(self):
    unused_command, output, unused_log = self.run_search(verbose=False, exact=False)
    self.assertNotIn("measured elapsed:", output)
    self.assertIn("QPS: 12345.6", output)
    self.assertIn("CPU cores used: 3.9", output)

  def test_failure_output_is_bounded_in_concise_and_complete_in_verbose(self):
    unused_command, concise_output, unused_log = self.run_search(verbose=False, exit_status=7)
    unused_command, verbose_output, unused_log = self.run_search(verbose=True, exit_status=7)

    for output in (concise_output, verbose_output):
      self.assertIn("SearchPerfTest failed with exit status 7", output)
      self.assertIn(".stdout", output)
      self.assertIn("line-59", output)
    self.assertNotIn("line-0\n", concise_output)
    self.assertIn("line-0", verbose_output)

  def run_search(self, verbose, exit_status=0, directory=None, exact=True):
    bench_util = self.load_bench_util()
    if exit_status == 0 and exact:
      child_output = b"---- MEASURED PHASE READY ----\n---- MEASURED PHASE COMPLETE ----\n"
    elif exit_status == 0:
      child_output = b""
    else:
      child_output = "".join(f"line-{line}\n" for line in range(60)).encode("utf-8")

    class Process:
      def __init__(self):
        self.stdout = io.BytesIO(child_output)

      def wait(self):
        return exit_status

    competition = types.SimpleNamespace(
      taskRepeatCount=20, taskCountPerCat=1, groupByCat=False,
      warmupTaskRepeatCount=1 if exact else None, measuredTaskRepeatCount=2 if exact else None,
      perfControl=False, perfEvents=None,
    )
    competitor = types.SimpleNamespace(
      checkout="checkout", name="candidate", doSort=False, javaCommand="java", directory="MMapDirectory",
      index=types.SimpleNamespace(getPath=lambda: "index", facets=None), analyzer="analyzer", tasksFile="tasks",
      numConcurrentQueries=1, competition=competition, searchConcurrency=0, similarity="similarity", commitPoint="multi",
      hiliteImpl="hilite", topN=10, testContext="", printHeap=False, pk=False, loadStoredFields=False,
      vectorDict=None, vectorFileName=None, vectorScale=None, exitable=False, pollute=False,
    )
    runner = bench_util.RunAlgs.__new__(bench_util.RunAlgs)
    runner.verbose = verbose
    runner.compute_qps = mock.Mock(return_value=(12345.6,))
    output = io.StringIO()

    ownedDirectory = tempfile.TemporaryDirectory() if directory is None else None
    if ownedDirectory is not None:
      directory = ownedDirectory.name
    try:
      with (
        mock.patch.object(bench_util.constants, "LOGS_DIR", directory),
        mock.patch.object(bench_util, "PERF_EXE", None),
        mock.patch.object(bench_util, "getClassPath", return_value=[]),
        mock.patch.object(bench_util, "classPathToString", return_value="classpath"),
        mock.patch.object(bench_util, "get_profiler_jvm_args", return_value=""),
        mock.patch.object(bench_util, "parseResults", return_value=([], None, 1234.0, 3.9)),
        mock.patch.object(bench_util.subprocess, "Popen", return_value=Process()) as popen,
        contextlib.redirect_stdout(output),
      ):
        if exit_status == 0:
          runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
        else:
          with self.assertRaisesRegex(RuntimeError, "SearchPerfTest failed"):
            runner.runSimpleSearchBench(0, "test", competitor, False, 1, 2)
      log_text = (Path(directory) / "test.candidate.0.stdout").read_text(encoding="utf-8")
    finally:
      if ownedDirectory is not None:
        ownedDirectory.cleanup()
    return popen.call_args.args[0], output.getvalue(), log_text

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
