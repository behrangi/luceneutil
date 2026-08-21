import importlib.util
import inspect
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def load_search_bench():
  bench_util = types.ModuleType("benchUtil")
  bench_util.RunAlgs = mock.Mock()
  common = types.ModuleType("common")
  common.osName = "test"
  constants = types.ModuleType("constants")
  constants.JAVA_COMMAND = "java"

  modules = {"benchUtil": bench_util, "common": common, "constants": constants}
  module_path = Path(__file__).with_name("searchBench.py")
  spec = importlib.util.spec_from_file_location("search_bench_query_filter_test", module_path)
  module = importlib.util.module_from_spec(spec)
  with mock.patch.dict(sys.modules, modules):
    spec.loader.exec_module(module)
  return module, bench_util


searchBench, bench_util = load_search_bench()


class Competitor:
  def __init__(self, tasksFile, name="competitor"):
    self.tasksFile = tasksFile
    self.name = name
    self.competition = types.SimpleNamespace(jvmCount=0)

  def getAggregateProfilerResult(self, unused_id, unused_mode, stackSize):
    return [(stackSize, "")]


class QueryFilteringTest(unittest.TestCase):
  def setUp(self):
    bench_util.RunAlgs.reset_mock()

  def test_parse_normal_category_line(self):
    self.assertEqual("HighTerm", searchBench.parseTaskCategory("HighTerm: body:test\n"))

  def test_parse_line_without_separator(self):
    self.assertIsNone(searchBench.parseTaskCategory("# comment\n"))

  def test_filter_preserves_line_without_separator(self):
    output = self.filter_tasks("# comment\nHighTerm: one\nLowTerm: two\n", ([r"^HighTerm$"], None))

    self.assertEqual("# comment\nHighTerm: one\n", output)

  def test_exact_positive_filtering(self):
    output = self.filter_tasks("HighTerm: one\nHighTermExtra: two\n", ([r"^HighTerm$"], None))

    self.assertEqual("HighTerm: one\n", output)

  def test_pk_only_produces_no_regular_task_lines(self):
    output = self.filter_tasks("# metadata\nHighTerm: one\nLowTerm: two\n", ([r"^PKLookup$"], None))

    self.assertEqual("# metadata\n", output)
    self.assertFalse(any(searchBench.parseTaskCategory(line) is not None for line in output.splitlines()))

  def test_both_competitors_receive_identical_filtered_file(self):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "source.tasks")
      destination = os.path.join(directory, "filtered.tasks")
      Path(source).write_text("HighTerm: one\n", encoding="utf-8")
      competitors = [Competitor(source), Competitor(source)]

      searchBench.filterTasksFile(competitors, source, destination, ([r"^HighTerm$"], None))

      self.assertEqual(destination, competitors[0].tasksFile)
      self.assertEqual(destination, competitors[1].tasksFile)

  def test_common_task_file_mismatch_fails_clearly(self):
    with self.assertRaisesRegex(RuntimeError, "inconsistent taskFile baseline.tasks vs candidate.tasks"):
      searchBench.commonTasksFile(Competitor("baseline.tasks"), Competitor("candidate.tasks"))

  def test_unknown_categories_are_reported_in_requested_order(self):
    with tempfile.TemporaryDirectory() as directory:
      tasks_file = os.path.join(directory, "tasks")
      Path(tasks_file).write_text("HighTerm: one\n", encoding="utf-8")

      with self.assertRaisesRegex(RuntimeError, "MissingTwo, MissingOne"):
        searchBench.validateTaskCategories(("MissingTwo", "MissingOne"), tasks_file)

  def test_category_validation_is_case_sensitive(self):
    with tempfile.TemporaryDirectory() as directory:
      tasks_file = os.path.join(directory, "tasks")
      Path(tasks_file).write_text("HighTerm: one\n", encoding="utf-8")

      with self.assertRaisesRegex(RuntimeError, "highterm"):
        searchBench.validateTaskCategories(("highterm",), tasks_file)

  def test_search_mismatch_fails_before_orchestration(self):
    with self.assertRaisesRegex(RuntimeError, "inconsistent taskFile"):
      searchBench.run(
        "test",
        Competitor("baseline.tasks"),
        Competitor("candidate.tasks"),
        search=True,
        randomSeed=0,
      )

    bench_util.RunAlgs.assert_not_called()

  def test_search_only_filters_without_index_creation(self):
    with tempfile.TemporaryDirectory() as directory:
      tasks_file = os.path.join(directory, "source.tasks")
      Path(tasks_file).write_text("HighTerm: one\nLowTerm: two\n", encoding="utf-8")
      base = Competitor(tasks_file, "base")
      challenger = Competitor(tasks_file, "challenger")
      runner = mock.Mock()
      runner.getSearchLogFiles.return_value = []
      bench_util.RunAlgs.return_value = runner
      searchBench.constants.BENCH_BASE_DIR = directory

      searchBench.run(
        "test",
        base,
        challenger,
        search=True,
        index=False,
        taskPatterns=([r"^HighTerm$"], None),
        randomSeed=0,
        requestedTaskCategories=("HighTerm",),
      )

    runner.makeIndex.assert_not_called()
    self.assertEqual(base.tasksFile, challenger.tasksFile)

  def test_run_signature_preserves_positional_compatibility(self):
    parameters = list(inspect.signature(searchBench.run).parameters)

    self.assertEqual(
      ["taskPatterns", "randomSeed", "requireOverlap", "skipReport", "requestedTaskCategories"],
      parameters[-5:],
    )

  def filter_tasks(self, contents, patterns):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "source.tasks")
      destination = os.path.join(directory, "filtered.tasks")
      Path(source).write_text(contents, encoding="utf-8")
      searchBench.filterTasksFile([], source, destination, patterns)
      return Path(destination).read_text(encoding="utf-8")


if __name__ == "__main__":
  unittest.main()
