import os
import sys
import types
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.modules.setdefault("competition", types.ModuleType("competition"))

import example


class StubCompetition:
  def __init__(self):
    self.calls = []

  def skipIndex(self):
    self.calls.append("skipIndex")

  def skipSearch(self):
    self.calls.append("skipSearch")


class StubParser:
  def error(self, message):
    raise ValueError(message)


class ExecutionModeTest(unittest.TestCase):
  def test_both_preserves_default_behavior(self):
    comp = StubCompetition()

    example.configure_mode(comp, "both")

    self.assertEqual([], comp.calls)

  def test_build_skips_search(self):
    comp = StubCompetition()

    example.configure_mode(comp, "build")

    self.assertEqual(["skipSearch"], comp.calls)

  def test_search_skips_index_creation(self):
    comp = StubCompetition()

    example.configure_mode(comp, "search")

    self.assertEqual(["skipIndex"], comp.calls)

  def test_relative_index_path_is_normalized(self):
    args = Namespace(index_path=os.path.join("relative", "canonical"), reindex=False)

    example.normalize_and_validate_options(StubParser(), args)

    expected_path = os.path.abspath(os.path.expanduser(os.path.join("relative", "canonical")))
    self.assertEqual(expected_path, args.index_path)

  def test_explicit_index_path_rejects_reindex(self):
    args = Namespace(index_path="canonical", reindex=True)

    with self.assertRaisesRegex(ValueError, "--index-path cannot be combined with --reindex"):
      example.normalize_and_validate_options(StubParser(), args)


if __name__ == "__main__":
  unittest.main()
