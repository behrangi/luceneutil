#!/usr/bin/env python

import dataclasses
import os
import re
import subprocess

import benchUtil
import constants


@dataclasses.dataclass(frozen=True)
class Config:
  indexPath: str
  docsPath: str
  queriesPath: str
  docCount: int
  dim: int
  topK: int
  fanout: int
  queryStartIndex: int
  queryCount: int
  searchThreads: int
  quantization: str
  maxConn: int = 32
  beamWidthIndex: int = 100
  metric: str = "dot_product"
  indexType: str = "hnsw"
  seed: int | None = None
  perfControl: bool = False
  perfEvents: tuple = ()
  profile: str = "jfr"
  jvmArgs: tuple = ()
  gc: str | None = None
  verbose: bool = False


_MEASURED_QUERIES = re.compile(r"^KNN measured queries: (\d+)$")
_MEASURED_ELAPSED = re.compile(r"^KNN measured elapsed sec: ([0-9.Ee+-]+)$")
_MEASURED_QPS = re.compile(r"^KNN measured QPS: ([0-9.Ee+-]+)$")
_SUMMARY = re.compile(r"^SUMMARY: (.*)$")
_SEED = re.compile(r"^Seed = (-?\d+)$")


def artifactPaths(outputDir, competitor, iteration):
  iterationDir = os.path.join(outputDir, competitor, f"iteration-{iteration}")
  return {
    "directory": iterationDir,
    "result": os.path.join(iterationDir, "result.log"),
    "process": os.path.join(iterationDir, "process.log"),
    "perf": os.path.join(iterationDir, "perf.stat"),
    "jfr": os.path.join(iterationDir, "profile.jfr"),
    "json": os.path.join(iterationDir, "result.json"),
  }


def buildCommand(config, checkout, paths, controlPath=None, ackPath=None):
  if config.perfControl != (controlPath is not None and ackPath is not None):
    raise ValueError("perf-control paths must be supplied exactly when perf control is enabled")
  command = []
  if config.perfControl:
    if benchUtil.PERF_EXE is None:
      raise RuntimeError("--perf-control requires a perf executable")
    command += [
      benchUtil.PERF_EXE, "stat", "-dd", "-x", ";", "--no-big-num", "-o", paths["perf"],
      "-e", ",".join(config.perfEvents), "--delay=-1", f"--control=fifo:{controlPath},{ackPath}",
    ]

  resolvedJava = benchUtil.resolveSearchJavaCommand(constants.JAVA_COMMAND, config.gc)
  javaExecutable = resolvedJava[0]
  jvmArgs = list(resolvedJava[1:])
  if config.profile == "jfr":
    jvmArgs.append(benchUtil.get_profiler_jvm_args(paths["jfr"], printInfo=config.verbose))
  jvmArgs += ["-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints"]
  jvmArgs += config.jvmArgs
  cp = benchUtil.classPathToString(benchUtil.getClassPath(checkout) + (f"{constants.BENCH_BASE_DIR}/build",))
  command += [javaExecutable, *jvmArgs, "-classpath", cp, "knn.KnnGraphTester"]
  command += [
    "-indexPath", config.indexPath,
    "-docs", config.docsPath,
    "-ndoc", str(config.docCount),
    "-dim", str(config.dim),
    "-encoding", "float32",
    "-metric", config.metric,
    "-indexType", config.indexType,
    "-maxConn", str(config.maxConn),
    "-beamWidthIndex", str(config.beamWidthIndex),
    "-topK", str(config.topK),
    "-fanout", str(config.fanout),
    "-numSearchThread", str(config.searchThreads),
    "-queryStartIndex", str(config.queryStartIndex),
    "-nquery", str(config.queryCount),
  ]
  if config.seed is not None:
    command += ["-seed", str(config.seed)]
  if config.quantization == "4bit-compressed":
    command += ["-quantize", "-quantizeBits", "4", "-quantizeCompress"]
  if config.perfControl:
    command += ["-perfControlPath", controlPath, "-perfAckPath", ackPath]
  command += ["-search", config.queriesPath]
  return command, javaExecutable, jvmArgs


def parseResult(processLog):
  values = {}
  summaryLine = None
  retained = []
  with open(processLog, encoding="utf-8") as f:
    for rawLine in f:
      line = rawLine.rstrip("\r\n")
      for name, pattern, conversion in (
        ("measured_tasks", _MEASURED_QUERIES, int),
        ("measured_elapsed_sec", _MEASURED_ELAPSED, float),
        ("qps", _MEASURED_QPS, float),
      ):
        match = pattern.match(line)
        if match is not None:
          values[name] = conversion(match.group(1))
          retained.append(line)
      match = _SUMMARY.match(line)
      if match is not None:
        summaryLine = match.group(1)
        retained.append(line)
      match = _SEED.match(line)
      if match is not None:
        values["seed"] = int(match.group(1))
        retained.append(line)
  missing = {"measured_tasks", "measured_elapsed_sec", "qps", "seed"} - values.keys()
  if missing or summaryLine is None:
    raise RuntimeError("KNN output is missing: %s" % ", ".join(sorted(missing | ({"SUMMARY"} if summaryLine is None else set()))))
  columns = summaryLine.split("\t")
  if len(columns) < 29:
    raise RuntimeError(f"KNN SUMMARY has {len(columns)} columns; expected at least 29")
  values.update(
    recall=float(columns[0]),
    latency_ms_per_query=float(columns[1]),
    cpu_ms_per_query=None if float(columns[2]) < 0 else float(columns[2]),
    average_cpu_cores=float(columns[3]),
    average_visited=int(columns[14]),
    segment_count=int(columns[19]),
    vector_ram_mb=float(columns[25]),
    retained_lines=retained,
  )
  return values


def buildResult(config, competitor, iteration, measured, perfData, javaExecutable, jvmArgs):
  return {
    "schema_version": 1,
    "benchmark": {
      "workload": "knn",
      "mode": "search",
      "index": config.indexPath,
      "doc_vectors": config.docsPath,
      "query_vectors": config.queriesPath,
      "doc_count": config.docCount,
      "dimensions": config.dim,
      "encoding": "float32",
      "metric": config.metric,
      "index_type": config.indexType,
      "max_conn": config.maxConn,
      "beam_width_index": config.beamWidthIndex,
      "quantization": config.quantization,
      "top_k": config.topK,
      "fanout": config.fanout,
      "query_start_index": config.queryStartIndex,
      "query_count": config.queryCount,
      "search_threads": config.searchThreads,
      "seed": measured["seed"],
      "measured_tasks": measured["measured_tasks"],
      "measured_elapsed_sec": measured["measured_elapsed_sec"],
      "qps": measured["qps"],
      "recall": measured["recall"],
      "latency_ms_per_query": measured["latency_ms_per_query"],
      "cpu_ms_per_query": measured["cpu_ms_per_query"],
      "average_cpu_cores": measured["average_cpu_cores"],
      "average_visited": measured["average_visited"],
      "vector_ram_mb": measured["vector_ram_mb"],
      "segment_count": measured["segment_count"],
    },
    "run": {"competitor": competitor, "iteration": iteration},
    "jvm": {"java": javaExecutable, "args": list(jvmArgs)},
    "profiling": {"type": config.profile},
    "perf": {
      "enabled": config.perfControl,
      "control": config.perfControl,
      "requested_events": list(config.perfEvents),
      "events": [] if perfData is None else perfData["events"],
      "metadata_lines": [] if perfData is None else perfData["metadata_lines"],
    },
  }


def runOne(config, checkout, competitor, iteration, outputDir):
  paths = artifactPaths(outputDir, competitor, iteration)
  os.makedirs(paths["directory"], exist_ok=False)
  with benchUtil.PerfControlResources(config.perfControl) as resources:
    command, javaExecutable, jvmArgs = buildCommand(config, checkout, paths, resources.controlPath, resources.ackPath)
    if config.verbose:
      print("COMMAND: %s" % " ".join(command))
    with open(paths["process"], "wb") as processLog:
      processLog.write(("COMMAND: %s\n" % " ".join(command)).encode("utf-8"))
      processLog.flush()
      process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
      while True:
        line = process.stdout.readline()
        if line == b"":
          break
        processLog.write(line)
        processLog.flush()
        if b"---- MEASURED PHASE READY ----" in line:
          print("  warmup complete")
          print("  measured phase ready")
        elif b"---- MEASURED PHASE COMPLETE ----" in line:
          print("  measured phase complete")
      exitStatus = process.wait()
  if exitStatus != 0:
    raise RuntimeError(f"KnnGraphTester failed with exit status {exitStatus}; see {paths['process']}")
  measured = parseResult(paths["process"])
  with open(paths["result"], "w", encoding="utf-8") as resultLog:
    for line in measured.pop("retained_lines"):
      resultLog.write(line + "\n")
  perfData = benchUtil.parsePerfStat(paths["perf"]) if config.perfControl else None
  result = buildResult(config, competitor, iteration, measured, perfData, javaExecutable, jvmArgs)
  benchUtil.writeJSONAtomically(paths["json"], result)
  print(f"  measured queries: {measured['measured_tasks']}")
  print(f"  measured elapsed: {measured['measured_elapsed_sec']:.3f} s")
  print(f"  QPS: {measured['qps']:.1f}")
  print(f"  recall: {measured['recall']:.3f}")
  print(f"  log: {paths['process']}")
  print(f"  result: {paths['json']}")
  return paths


def run(config, competitors, iterations, outputDir):
  for competitor, checkout in competitors:
    for iteration in range(iterations):
      print(f"[{iteration + 1}/{iterations}] {competitor}")
      runOne(config, checkout, competitor, iteration, outputDir)
