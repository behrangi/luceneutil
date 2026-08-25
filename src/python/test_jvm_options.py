import contextlib
import io
import importlib.util
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_perf_stat_output import load_bench_util, run_search


class JVMOptionsTest(unittest.TestCase):
  def test_default_and_opt_in_commands_preserve_application_and_perf_arguments(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      default_command, unused_process, unused_perf = run_search(bench_util, run_directory, "perf", perf_control=True)
    with tempfile.TemporaryDirectory() as run_directory:
      configured_command, unused_process, unused_perf = run_search(
        bench_util, run_directory, "perf", perf_control=True, profile="none",
        jvm_args=("-XX:+AlwaysPreTouch", "-XX:CompileCommand=print,foo.Bar::method with space"),
      )

    default_java = default_command.index("java")
    configured_java = configured_command.index("java")
    def perf_arguments(command, java_index):
      arguments = list(command[:java_index])
      arguments[arguments.index("-o") + 1] = "<perf.stat>"
      return arguments

    self.assertEqual(perf_arguments(default_command, default_java), perf_arguments(configured_command, configured_java))
    def application_arguments(command):
      arguments = list(command[command.index("-classpath"):])
      log_index = arguments.index("-log")
      arguments[log_index + 1] = "<result.log>"
      return arguments
    self.assertEqual(
      application_arguments(default_command),
      application_arguments(configured_command),
    )
    configured_jvm = configured_command[configured_java + 1:configured_command.index("-classpath")]
    self.assertEqual(
      ["-XX:+AlwaysPreTouch", "-XX:CompileCommand=print,foo.Bar::method with space"],
      configured_jvm[-2:],
    )
    self.assertNotIn("with", configured_jvm)

  def test_jfr_default_is_preserved_and_none_has_no_jfr_argument_or_artifact(self):
    bench_util = load_bench_util()
    with tempfile.TemporaryDirectory() as run_directory:
      jfr_command, unused_process, unused_perf = run_search(bench_util, run_directory, None)
      jfr_path = os.path.join(run_directory, "baseline", "iteration-0", "profile.jfr")
      self.assertIn(f"JFR:{jfr_path}", jfr_command)
      self.assertTrue(bench_util.get_profiler_jvm_args(jfr_path, printInfo=False).startswith("-XX:StartFlightRecording="))

    with tempfile.TemporaryDirectory() as run_directory:
      none_command, unused_process, unused_perf = run_search(bench_util, run_directory, None, profile="none")
      jfr_path = os.path.join(run_directory, "baseline", "iteration-0", "profile.jfr")
      self.assertFalse(any(argument.startswith(("-XX:StartFlightRecording=", "JFR:")) for argument in none_command))
      self.assertFalse(os.path.exists(jfr_path))

  def test_gc_selection_replaces_or_removes_only_parallel_default(self):
    bench_util = load_bench_util()
    original = "java -server -Xmx2g -XX:+UseParallelGC"
    self.assertEqual(
      ["java", "-server", "-Xmx2g", "-XX:+UseParallelGC"],
      bench_util.resolveSearchJavaCommand(original),
    )
    self.assertEqual("-XX:+UseG1GC", bench_util.resolveSearchJavaCommand(original, "g1")[-1])
    self.assertNotIn("-XX:+UseParallelGC", bench_util.resolveSearchJavaCommand(original, "default"))
    self.assertEqual(["java", "-server"], bench_util.resolveSearchJavaCommand("java -server", "default"))
    self.assertEqual("-XX:+UseG1GC", bench_util.resolveSearchJavaCommand("java -server", "g1")[-1])
    with self.assertRaisesRegex(RuntimeError, "must use --gc"):
      bench_util.validateExtraJVMArgs(("-XX:+UseG1GC",))

  def test_profile_none_skips_jfr_aggregation(self):
    bench_util = load_bench_util()
    spec = importlib.util.spec_from_file_location("competition_for_jvm_test", Path(__file__).with_name("competition.py"))
    competition = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"benchUtil": bench_util, "constants": bench_util.constants}):
      spec.loader.exec_module(competition)

    competitor = competition.Competitor.__new__(competition.Competitor)
    competitor.competition = types.SimpleNamespace(profile="none")
    self.assertEqual([], competitor.getAggregateProfilerResult("test", "cpu"))

  def test_cli_preserves_repeated_jvm_arguments_and_profile(self):
    with tempfile.TemporaryDirectory() as output_root:
      comp = run_example(
        output_root,
        "--jvm-arg=-XX:+AlwaysPreTouch",
        "--jvm-arg=-XX:CompileCommand=print,foo.Bar::method",
        "--profile", "none", "--gc", "g1",
      )
    self.assertEqual(("-XX:+AlwaysPreTouch", "-XX:CompileCommand=print,foo.Bar::method"), tuple(comp.options["jvmArgs"]))
    self.assertEqual("none", comp.options["profile"])
    self.assertEqual("g1", comp.options["gc"])

  def test_cli_rejects_gc_selector_as_generic_jvm_argument(self):
    stderr = io.StringIO()
    with tempfile.TemporaryDirectory() as output_root:
      with self.assertRaises(SystemExit), contextlib.redirect_stderr(stderr):
        run_example(output_root, "--jvm-arg=-XX:+UseG1GC")
    self.assertIn("must use --gc", stderr.getvalue())


class FakeCompetition:
  instance = None

  def __init__(self, **kwargs):
    FakeCompetition.instance = self
    self.options = kwargs
    self.randomSeed = 0 if kwargs.get("randomSeed") is None else kwargs["randomSeed"]

  def skipIndex(self):
    pass

  def skipSearch(self):
    pass

  def addTaskPattern(self, unused_pattern):
    pass

  def setRequestedTaskCategories(self, unused_categories):
    pass

  def newIndex(self, *unused_args, **unused_kwargs):
    return types.SimpleNamespace(getPath=lambda: "/index")

  def competitor(self, *unused_args, **unused_kwargs):
    pass

  def benchmark(self, unused_id):
    pass


def run_example(output_root, *arguments):
  module = types.ModuleType("competition")
  module.Competition = FakeCompetition
  module.sourceData = lambda unused_source: object()
  module.constants = types.SimpleNamespace(LOGS_DIR=output_root, SEARCH_NUM_CONCURRENT_QUERIES=1)
  runner = str(Path(__file__).with_name("example.py"))
  with (
    mock.patch.dict(sys.modules, {"competition": module}),
    mock.patch.object(sys, "argv", [runner, "--source", "test", "--output-root", output_root, *arguments]),
    contextlib.redirect_stdout(io.StringIO()),
  ):
    runpy.run_path(runner, run_name="__main__")
  return FakeCompetition.instance


if __name__ == "__main__":
  unittest.main()
