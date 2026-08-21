import sys
import types
import unittest

sys.modules.setdefault("competition", types.ModuleType("competition"))

import example


class StubCompetition:
  def __init__(self):
    self.calls = []

  def skipIndex(self):
    self.calls.append("skipIndex")

  def skipSearch(self):
    self.calls.append("skipSearch")


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


if __name__ == "__main__":
  unittest.main()
