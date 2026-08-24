import builtins
import contextlib
import io
import os
import runpy
import sys
import types
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.modules.setdefault("competition", types.ModuleType("competition"))

import example


class StubParser:
  def error(self, message):
    raise ValueError(message)


class StubCompetition:
  def __init__(self):
    self.patterns = []
    self.categories = None

  def addTaskPattern(self, pattern):
    self.patterns.append(pattern)

  def setRequestedTaskCategories(self, categories):
    self.categories = tuple(categories)


class RunnerCompetition:
  instance = None

  def __init__(self, **kwargs):
    RunnerCompetition.instance = self
    suppliedSeed = kwargs.get("randomSeed")
    self.randomSeed = 0 if suppliedSeed is None else suppliedSeed
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


def args(queries, mode="search"):
  return Namespace(queries=queries, mode=mode)


class QuerySelectionTest(unittest.TestCase):
  def test_all_preserves_default_pk_behavior(self):
    requested = example.parseRequestedTaskCategories(StubParser(), args(" all "))
    comp = StubCompetition()

    includePK = example.configureTaskCategories(comp, requested)

    self.assertIsNone(requested)
    self.assertTrue(includePK)
    self.assertEqual([], comp.patterns)
    self.assertIsNone(comp.categories)

  def test_one_regular_category_disables_pk(self):
    requested = example.parseRequestedTaskCategories(StubParser(), args("HighTerm"))
    comp = StubCompetition()

    includePK = example.configureTaskCategories(comp, requested)

    self.assertEqual(("HighTerm",), requested)
    self.assertFalse(includePK)
    self.assertEqual(["^HighTerm$"], comp.patterns)

  def test_multiple_categories_trim_and_deduplicate_in_order(self):
    requested = example.parseRequestedTaskCategories(
      StubParser(),
      args(" HighTerm, AndHighHigh,HighPhrase, HighTerm "),
    )

    self.assertEqual(("HighTerm", "AndHighHigh", "HighPhrase"), requested)

  def test_empty_argument_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "--queries must not be empty"):
      example.parseRequestedTaskCategories(StubParser(), args("  "))

  def test_empty_entry_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "--queries contains an empty category"):
      example.parseRequestedTaskCategories(StubParser(), args("HighTerm,,HighPhrase"))

  def test_all_must_be_entire_argument(self):
    with self.assertRaisesRegex(ValueError, "'all' is valid only as the entire"):
      example.parseRequestedTaskCategories(StubParser(), args("all,HighTerm"))

  def test_regex_metacharacters_are_escaped_and_anchored(self):
    comp = StubCompetition()

    example.configureTaskCategories(comp, ("Category.+",))

    self.assertEqual([r"^Category\.\+$"], comp.patterns)

  def test_pk_only_enables_independent_pk(self):
    comp = StubCompetition()

    includePK = example.configureTaskCategories(comp, ("PKLookup",))

    self.assertTrue(includePK)
    self.assertEqual(["^PKLookup$"], comp.patterns)

  def test_mixed_regular_and_pk_enables_pk(self):
    comp = StubCompetition()

    includePK = example.configureTaskCategories(comp, ("HighTerm", "PKLookup"))

    self.assertTrue(includePK)
    self.assertEqual(["^HighTerm$", "^PKLookup$"], comp.patterns)

  def test_build_only_all_does_not_inspect_task_file(self):
    with mock.patch.object(builtins, "open", side_effect=AssertionError("task file must not be inspected")):
      requested = example.parseRequestedTaskCategories(StubParser(), args("all", mode="build"))

    self.assertIsNone(requested)

  def test_build_only_explicit_selection_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "--queries applies only when search is enabled"):
      example.parseRequestedTaskCategories(StubParser(), args("HighTerm", mode="build"))

  def test_runner_gives_both_competitors_identical_pk_setting(self):
    competition_module = sys.modules["competition"]
    runner_path = str(Path(example.__file__))
    for queries, expected_pk in (("HighTerm", False), ("HighTerm,PKLookup", True)):
      argv = [runner_path, "--source", "test", "--queries", queries]
      with (
        mock.patch.object(competition_module, "Competition", RunnerCompetition, create=True),
        mock.patch.object(competition_module, "sourceData", return_value=object(), create=True),
        mock.patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(io.StringIO()),
      ):
        runpy.run_path(runner_path, run_name="__main__")

      competitors = RunnerCompetition.instance.competitors
      self.assertEqual(2, len(competitors))
      self.assertEqual(expected_pk, competitors[0][2]["pk"])
      self.assertEqual(expected_pk, competitors[1][2]["pk"])
      self.assertIs(competitors[0][2]["index"], competitors[1][2]["index"])


if __name__ == "__main__":
  unittest.main()
