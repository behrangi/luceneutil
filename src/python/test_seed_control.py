import contextlib
import io
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


PYTHON_DIR = Path(__file__).parent
sys.path.insert(0, str(PYTHON_DIR))
sys.modules.setdefault("competition", types.ModuleType("competition"))

import example


class RunnerCompetition:
  instance = None
  generatedSeed = 8675309

  def __init__(self, **kwargs):
    RunnerCompetition.instance = self
    self.options = kwargs
    suppliedSeed = kwargs.get("randomSeed")
    self.randomSeed = self.generatedSeed if suppliedSeed is None else suppliedSeed
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


class SeedControlTest(unittest.TestCase):
  def run_runner(self, *arguments):
    competition_module = sys.modules["competition"]
    runner_path = str(Path(example.__file__))
    RunnerCompetition.instance = None
    output = io.StringIO()
    with (
      mock.patch.object(competition_module, "Competition", RunnerCompetition, create=True),
      mock.patch.object(competition_module, "sourceData", return_value=object(), create=True),
      mock.patch.object(sys, "argv", [runner_path, "--source", "test", *arguments]),
      contextlib.redirect_stdout(output),
    ):
      runpy.run_path(runner_path, run_name="__main__")
    return RunnerCompetition.instance, output.getvalue()

  def test_zero_positive_and_negative_seeds_are_accepted(self):
    for seed in (0, 12345, -9876):
      with self.subTest(seed=seed):
        competition, output = self.run_runner("--seed", str(seed))
        self.assertEqual(seed, competition.randomSeed)
        self.assertEqual(seed, competition.options["randomSeed"])
        self.assertIn(f"  seed: {seed}\n", output)

  def test_seed_reaches_exact_phase_competition(self):
    competition, unused_output = self.run_runner(
      "--seed", "42",
      "--warmup-repetitions", "0",
      "--measured-repetitions", "1",
      "--tasks-per-category", "1",
    )
    self.assertEqual(42, competition.options["randomSeed"])

  def test_omission_preserves_competition_generated_seed(self):
    competition, output = self.run_runner()
    self.assertIsNone(competition.options["randomSeed"])
    self.assertEqual(RunnerCompetition.generatedSeed, competition.randomSeed)
    self.assertIn(f"  seed: {RunnerCompetition.generatedSeed}\n", output)

  def test_existing_defaults_are_unchanged(self):
    competition, unused_output = self.run_runner()
    self.assertEqual(20, competition.options["jvmCount"])
    self.assertEqual(20, competition.options["taskRepeatCount"])
    self.assertFalse(competition.options["verbose"])
    for unused_name, unused_checkout, options in competition.competitors:
      self.assertNotIn("numConcurrentQueries", options)
      self.assertEqual(-1, options["searchConcurrency"])


if __name__ == "__main__":
  unittest.main()
