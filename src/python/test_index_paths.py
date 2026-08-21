import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def load_competition():
  constants = types.ModuleType("constants")
  values = {
    "ANALYZER_DEFAULT": "analyzer",
    "COMBINED_FIELDS_TASKS_FILE": "combined.tasks",
    "COMBINED_FIELDS_UNEVENLY_WEIGHTED_TASKS_FILE": "combined-weighted.tasks",
    "DISJUNCTION_DOC_COUNT": 1,
    "DISJUNCTION_DOCS_LINE_FILE": "disjunction.docs",
    "DISJUNCTION_INTENSIVE_TASKS_FILE": "disjunction-intensive.tasks",
    "DISJUNCTION_REALISTIC_TASKS_FILE": "disjunction-realistic.tasks",
    "DISJUNCTION_SIMPLE_TASKS_FILE": "disjunction-simple.tasks",
    "EUROPARL_MEDIUM_DOCS_LINE_FILE": "europarl.docs",
    "EUROPARL_MEDIUM_TASKS_FILE": "europarl.tasks",
    "FACET_FIELD_DV_FORMAT_DEFAULT": "facet-dv",
    "ID_FIELD_POSTINGS_FORMAT_DEFAULT": "id-postings",
    "INDEX_NUM_THREADS": 1,
    "JAVA_COMMAND": "java",
    "JAVAC_EXE": "javac",
    "LOGS_DIR": "logs",
    "MERGEPOLICY_DEFAULT": "merge-policy",
    "POSTINGS_FORMAT_DEFAULT": "postings",
    "SEARCH_NUM_CONCURRENT_QUERIES": 1,
    "SIMILARITY_DEFAULT": "similarity",
    "WIKI_BIG_DOCS_COUNT": 1,
    "WIKI_BIG_DOCS_LINE_FILE": "wiki-big.docs",
    "WIKI_MEDIUM_DOCS_COUNT": 1,
    "WIKI_MEDIUM_DOCS_LINE_FILE": "wiki-medium.docs",
    "WIKI_MEDIUM_FACETS_TASKS_10MDOCS_FILE": "wiki-facets.tasks",
    "WIKI_MEDIUM_TASKS_10MDOCS_FILE": "wiki-10m.tasks",
    "WIKI_MEDIUM_TASKS_1MDOCS_FILE": "wiki-1m.tasks",
    "WIKI_MEDIUM_TASKS_500DOCS_FILE": "wiki-500.tasks",
    "WIKI_VECTOR_TASKS_FILE": "wiki-vector.tasks",
  }
  for name, value in values.items():
    setattr(constants, name, value)

  bench_util = types.ModuleType("benchUtil")
  bench_util.checkoutToName = lambda checkout: checkout
  bench_util.checkoutToPath = lambda checkout: checkout
  bench_util.nameToIndexPath = lambda name: f"generated/{name}"

  search_bench = types.ModuleType("searchBench")
  search_bench.run = mock.Mock()

  modules = {
    "benchUtil": bench_util,
    "common": types.ModuleType("common"),
    "constants": constants,
    "searchBench": search_bench,
  }
  module_path = Path(__file__).with_name("competition.py")
  spec = importlib.util.spec_from_file_location("competition_index_path_test", module_path)
  module = importlib.util.module_from_spec(spec)
  with mock.patch.dict(sys.modules, modules):
    spec.loader.exec_module(module)
  return module, search_bench


competition, search_bench = load_competition()


class IndexPathTest(unittest.TestCase):
  def setUp(self):
    search_bench.run.reset_mock()
    self.data = competition.Data("data", "docs", 100, "tasks")

  def test_generated_path_behavior_is_unchanged(self):
    index = competition.Index("checkout", self.data)

    self.assertEqual(f"generated/{index.getName()}", index.getPath())
    self.assertFalse(index.hasExplicitPath())

  def test_explicit_absolute_path_is_returned_unchanged(self):
    with tempfile.TemporaryDirectory() as parent:
      index_path = os.path.join(parent, "canonical-index")
      index = competition.Index("checkout", self.data, indexPath=index_path)

      self.assertEqual(index_path, index.getPath())
      self.assertTrue(index.hasExplicitPath())

  def test_search_only_missing_explicit_path_fails_before_orchestration(self):
    with tempfile.TemporaryDirectory() as parent:
      missing_path = os.path.join(parent, "missing-index")
      self.assertFalse(os.path.exists(missing_path))
      index = competition.Index("checkout", self.data, indexPath=missing_path)
      comp = self.new_competition(index)
      comp.skipIndex()

      with self.assertRaisesRegex(RuntimeError, "search-only index path does not exist or is not a directory"):
        comp.benchmark("test")

    search_bench.run.assert_not_called()

  def test_build_only_rejects_existing_explicit_path(self):
    with tempfile.TemporaryDirectory() as index_path:
      index = competition.Index("checkout", self.data, indexPath=index_path)
      comp = self.new_competition(index)
      comp.skipSearch()

      with self.assertRaisesRegex(RuntimeError, "build-only index path already exists"):
        comp.benchmark("test")

    search_bench.run.assert_not_called()

  def test_search_only_passes_index_false_to_orchestration(self):
    with tempfile.TemporaryDirectory() as index_path:
      index = competition.Index("checkout", self.data, indexPath=index_path)
      comp = self.new_competition(index)
      comp.skipIndex()

      comp.benchmark("test")

    self.assertFalse(search_bench.run.call_args.kwargs["index"])

  def test_both_mode_reuses_existing_explicit_directory(self):
    with tempfile.TemporaryDirectory() as index_path:
      index = competition.Index("checkout", self.data, indexPath=index_path)
      comp = self.new_competition(index)

      comp.benchmark("test")

    search_bench.run.assert_called_once()
    self.assertTrue(search_bench.run.call_args.kwargs["index"])
    self.assertTrue(search_bench.run.call_args.kwargs["search"])

  def test_both_mode_rejects_explicit_regular_file(self):
    with tempfile.TemporaryDirectory() as parent:
      index_path = os.path.join(parent, "index-file")
      Path(index_path).touch()
      index = competition.Index("checkout", self.data, indexPath=index_path)
      comp = self.new_competition(index)

      with self.assertRaisesRegex(RuntimeError, "index path exists but is not a directory"):
        comp.benchmark("test")

    search_bench.run.assert_not_called()

  def test_competitors_share_explicit_canonical_index(self):
    with tempfile.TemporaryDirectory() as parent:
      index_path = os.path.join(parent, "canonical-index")
      index = competition.Index("checkout", self.data, indexPath=index_path)
      comp = self.new_competition(index)

      self.assertIs(index, comp.competitors[0].index)
      self.assertIs(index, comp.competitors[1].index)
      self.assertEqual(index_path, comp.competitors[0].index.getPath())
      self.assertEqual(index_path, comp.competitors[1].index.getPath())

  def test_requested_task_categories_are_immutable(self):
    categories = ["HighTerm", "PKLookup"]
    comp = competition.Competition(randomSeed=0)

    comp.setRequestedTaskCategories(categories)
    categories.append("LowTerm")

    self.assertEqual(("HighTerm", "PKLookup"), comp.requestedTaskCategories)

  def new_competition(self, index):
    comp = competition.Competition(randomSeed=0)
    comp.indices.append(index)
    comp.competitor("baseline", "baseline", index=index)
    comp.competitor("candidate", "candidate", index=index)
    return comp


if __name__ == "__main__":
  unittest.main()
