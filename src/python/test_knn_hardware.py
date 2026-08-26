import contextlib
import importlib.util
import io
import json
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


PYTHON_DIR = Path(__file__).parent
ROOT = PYTHON_DIR.parents[1]


def load_runner_module(perf_exe="/usr/bin/perf"):
  bench = types.ModuleType("benchUtil")
  bench.PERF_EXE = perf_exe
  bench.resolveSearchJavaCommand = lambda unused, gc: ["java", "-server", "-XX:+UseParallelGC"]
  bench.get_profiler_jvm_args = lambda path, printInfo=False: f"JFR:{path}"
  bench.getClassPath = lambda checkout: (f"{checkout}/lucene-core.jar",)
  bench.classPathToString = lambda paths: os.pathsep.join(paths)
  bench.PerfControlResources = None
  bench.parsePerfStat = lambda path: {"events": [], "metadata_lines": []}
  bench.writeJSONAtomically = lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8")
  constants = types.ModuleType("constants")
  constants.JAVA_COMMAND = "java -server -XX:+UseParallelGC"
  constants.BENCH_BASE_DIR = "/luceneutil"
  spec = importlib.util.spec_from_file_location("knnHardwareBench_test", PYTHON_DIR / "knnHardwareBench.py")
  module = importlib.util.module_from_spec(spec)
  with mock.patch.dict(sys.modules, {"benchUtil": bench, "constants": constants}):
    spec.loader.exec_module(module)
  return module, bench


class KnnHardwareCommandTest(unittest.TestCase):
  def config(self, module, **changes):
    values = dict(
      indexPath="/indices/knn", docsPath="/data/docs.vec", queriesPath="/data/queries.vec",
      docCount=1_000_000, dim=1024, topK=100, fanout=100, queryStartIndex=7,
      queryCount=123, searchThreads=4, quantization="float", seed=0,
      perfControl=True, perfEvents=("cycles", "instructions"), profile="none",
      jvmArgs=("-XX:+AlwaysPreTouch",),
    )
    values.update(changes)
    return module.Config(**values)

  def test_float_command_and_control_boundary_arguments(self):
    module, unused = load_runner_module()
    paths = module.artifactPaths("/runs/one", "baseline", 0)
    command, java, jvm = module.buildCommand(self.config(module), "/lucene", paths, "/tmp/control", "/tmp/ack")
    self.assertEqual("java", java)
    self.assertIn("-XX:+AlwaysPreTouch", jvm)
    self.assertEqual(paths["perf"], command[command.index("-o") + 1])
    self.assertIn("--delay=-1", command)
    self.assertIn("--control=fifo:/tmp/control,/tmp/ack", command)
    self.assertEqual("/tmp/control", command[command.index("-perfControlPath") + 1])
    self.assertEqual("/tmp/ack", command[command.index("-perfAckPath") + 1])
    self.assertEqual("/data/queries.vec", command[command.index("-search") + 1])
    self.assertNotIn("-reindex", command)
    self.assertNotIn("-forceMerge", command)
    self.assertNotIn("-quantize", command)

  def test_compressed_four_bit_command(self):
    module, unused = load_runner_module()
    paths = module.artifactPaths("/runs/one", "candidate", 2)
    command, unused_java, unused_jvm = module.buildCommand(
      self.config(module, quantization="4bit-compressed"), "/lucene", paths, "/tmp/c", "/tmp/a"
    )
    self.assertEqual("4", command[command.index("-quantizeBits") + 1])
    self.assertIn("-quantize", command)
    self.assertIn("-quantizeCompress", command)
    self.assertNotIn("-reindex", command)
    self.assertNotIn("-forceMerge", command)

  def test_competitors_and_iterations_have_distinct_artifacts(self):
    module, unused = load_runner_module()
    paths = {
      module.artifactPaths("/runs/one", competitor, iteration)["perf"]
      for competitor in ("baseline", "my_modified_version") for iteration in range(2)
    }
    self.assertEqual(4, len(paths))

  def test_result_schema_records_configuration_and_measurement(self):
    module, unused = load_runner_module()
    measured = {
      "measured_tasks": 100, "measured_elapsed_sec": 0.25, "qps": 400.0,
      "recall": 0.91, "latency_ms_per_query": 2.5, "cpu_ms_per_query": 1.2,
      "average_cpu_cores": 0.48, "average_visited": 321,
      "segment_count": 4, "vector_ram_mb": 512.0, "seed": 0,
    }
    perf = {"events": [{"name": "cycles", "value": 10}], "metadata_lines": []}
    result = module.buildResult(self.config(module), "baseline", 0, measured, perf, "java", ("-server",))
    self.assertEqual(1, result["schema_version"])
    self.assertEqual("knn", result["benchmark"]["workload"])
    self.assertEqual(100, result["benchmark"]["measured_tasks"])
    self.assertEqual(0.91, result["benchmark"]["recall"])
    self.assertEqual(2.5, result["benchmark"]["latency_ms_per_query"])
    self.assertEqual(0.48, result["benchmark"]["average_cpu_cores"])
    self.assertEqual(321, result["benchmark"]["average_visited"])
    self.assertEqual(["cycles", "instructions"], result["perf"]["requested_events"])

  def test_parse_result_uses_explicit_measurement_and_summary(self):
    module, unused = load_runner_module()
    columns = ["0.875", "2.0", "1.5", "0.75", "1000000", "KNN", "100", "100", "N/A", "N/A", "100", "32", "100", "4 bits", "456", "1", "1", "1", "-1", "3", "100", "null", "N/A", "1", "200", "300", "false", "HNSW", "no"]
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
      f.write("Seed = 0\nKNN measured queries: 100\nKNN measured elapsed sec: 0.250000000\nKNN measured QPS: 400.000000000\n")
      f.write("SUMMARY: " + "\t".join(columns) + "\n")
      path = f.name
    try:
      result = module.parseResult(path)
    finally:
      os.unlink(path)
    self.assertEqual(100, result["measured_tasks"])
    self.assertEqual(0.25, result["measured_elapsed_sec"])
    self.assertEqual(0.875, result["recall"])
    self.assertEqual(2.0, result["latency_ms_per_query"])
    self.assertEqual(0.75, result["average_cpu_cores"])
    self.assertEqual(456, result["average_visited"])

  def test_success_publishes_iteration_artifacts_and_json(self):
    module, bench = load_runner_module()
    class Resources:
      def __init__(self, enabled):
        self.controlPath = "/tmp/control" if enabled else None
        self.ackPath = "/tmp/ack" if enabled else None
      def __enter__(self):
        return self
      def __exit__(self, *unused):
        pass
    bench.PerfControlResources = Resources
    columns = ["0.875", "2.0", "1.5", "0.75", "1000000", "KNN", "100", "100", "N/A", "N/A", "100", "32", "100", "no", "456", "1", "1", "1", "-1", "3", "100", "null", "N/A", "1", "200", "300", "false", "HNSW", "no"]
    output = (
      "Seed = 0\ndone warmup\n---- MEASURED PHASE READY ----\n---- MEASURED PHASE COMPLETE ----\n"
      "KNN measured queries: 100\nKNN measured elapsed sec: 0.250000000\nKNN measured QPS: 400.000000000\n"
      "SUMMARY: " + "\t".join(columns) + "\n"
    ).encode()
    class Process:
      def __init__(self):
        self.stdout = io.BytesIO(output)
      def wait(self):
        return 0
    with tempfile.TemporaryDirectory() as root, mock.patch.object(module.subprocess, "Popen", return_value=Process()):
      paths = module.runOne(self.config(module), "/lucene", "baseline", 0, root)
      result = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
      self.assertTrue(Path(paths["process"]).is_file())
      self.assertTrue(Path(paths["result"]).is_file())
      self.assertEqual("knn", result["benchmark"]["workload"])
      self.assertEqual(400.0, result["benchmark"]["qps"])

  def test_failed_process_does_not_publish_result_json(self):
    module, bench = load_runner_module(perf_exe=None)
    class Resources:
      controlPath = ackPath = None
      def __init__(self, unused): pass
      def __enter__(self): return self
      def __exit__(self, *unused): pass
    bench.PerfControlResources = Resources
    class Process:
      stdout = io.BytesIO(b"failure\n")
      def wait(self): return 3
    config = self.config(module, perfControl=False, perfEvents=())
    with tempfile.TemporaryDirectory() as root, mock.patch.object(module.subprocess, "Popen", return_value=Process()):
      with self.assertRaisesRegex(RuntimeError, "exit status 3"):
        module.runOne(config, "/lucene", "baseline", 0, root)
      self.assertFalse(Path(module.artifactPaths(root, "baseline", 0)["json"]).exists())

  def test_java_boundary_order_and_ground_truth_precedes_search(self):
    source = (ROOT / "src/main/knn/KnnGraphTester.java").read_text(encoding="utf-8")
    dispatch = source.index("ExactNNResult exactNN = getExactNN")
    test_search = source.index("private void testSearch")
    self.assertLess(dispatch, test_search)
    body = source[test_search:source.index("private void collectHnswTraversalScores", test_search)]
    positions = [
      body.index('log("done warmup'),
      body.index("---- MEASURED PHASE READY ----"),
      body.index("perfControl.enableAndWaitForAck();"),
      body.index("measuredStartNS = System.nanoTime();"),
      body.index("for (int i = 0; i < numQueryVectors; i++)", body.index("measuredStartNS = System.nanoTime();")),
      body.index("measuredEndNS = System.nanoTime();"),
      body.index("perfControl.disableAndWaitForAck();"),
      body.index("---- MEASURED PHASE COMPLETE ----"),
      body.index("ThreadDetails endThreadDetails = new ThreadDetails();"),
      body.index("StoredFields storedFields"),
    ]
    self.assertEqual(positions, sorted(positions))


class KnnHardwareCLITest(unittest.TestCase):
  def run_example(self, *extra):
    with tempfile.TemporaryDirectory() as temp:
      index = Path(temp, "index"); index.mkdir()
      docs = Path(temp, "docs.vec"); docs.write_bytes(b"docs")
      queries = Path(temp, "queries.vec"); queries.write_bytes(b"queries")
      competition = types.ModuleType("competition")
      competition.constants = types.SimpleNamespace(LOGS_DIR=temp)
      competition.benchUtil = types.SimpleNamespace(PERF_STATS=("cycles", "instructions"))
      knn = types.ModuleType("knnHardwareBench")
      captured = {}
      class Config:
        def __init__(self, **kwargs):
          self.__dict__.update(kwargs)
      knn.Config = Config
      def run(config, competitors, iterations, outputDir):
        captured.update(config=config, competitors=competitors, iterations=iterations, outputDir=outputDir)
      knn.run = run
      runner = str(PYTHON_DIR / "example.py")
      argv = [
        runner, "--workload", "knn", "--mode", "search", "--iterations", "1",
        "--output-root", temp, "--knn-index-path", str(index), "--knn-docs", str(docs),
        "--knn-queries", str(queries), "--knn-doc-count", "1000000", "--knn-dim", "1024", *extra,
      ]
      with (
        mock.patch.dict(sys.modules, {"competition": competition, "knnHardwareBench": knn}),
        mock.patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(io.StringIO()),
        self.assertRaises(SystemExit) as exited,
      ):
        runpy.run_path(runner, run_name="__main__")
      self.assertEqual(0, exited.exception.code)
      return captured

  def test_cli_propagates_float_and_explicit_values(self):
    captured = self.run_example(
      "--knn-top-k", "25", "--knn-fanout", "75", "--knn-query-start-index", "9",
      "--knn-query-count", "100", "--knn-search-threads", "4", "--seed", "7",
    )
    config = captured["config"]
    self.assertEqual((25, 75, 9, 100, 4, 7), (config.topK, config.fanout, config.queryStartIndex, config.queryCount, config.searchThreads, config.seed))
    self.assertEqual("float", config.quantization)

  def test_cli_propagates_compressed_and_shared_tool_options(self):
    config = self.run_example(
      "--knn-quantization", "4bit-compressed", "--perf-control", "--perf-events", "cycles,instructions",
      "--profile", "none", "--gc", "g1", "--jvm-arg=-XX:+AlwaysPreTouch",
    )["config"]
    self.assertEqual("4bit-compressed", config.quantization)
    self.assertTrue(config.perfControl)
    self.assertEqual(("cycles", "instructions"), config.perfEvents)
    self.assertEqual("none", config.profile)
    self.assertEqual(("-XX:+AlwaysPreTouch",), config.jvmArgs)

  def test_cli_rejects_build_and_reindex(self):
    runner = str(PYTHON_DIR / "example.py")
    competition = types.ModuleType("competition")
    with mock.patch.dict(sys.modules, {"competition": competition}), mock.patch.object(sys, "argv", [runner, "--workload", "knn", "--mode", "build"]), self.assertRaises(SystemExit):
      runpy.run_path(runner, run_name="__main__")


if __name__ == "__main__":
  unittest.main()
