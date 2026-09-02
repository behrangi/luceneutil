#!/usr/bin/env python

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import datetime
import os
import re
import secrets
import sys

import competition


def createRunDirectory(outputRoot, now=None, randomSuffix=None):
  outputRoot = os.path.abspath(os.path.expanduser(outputRoot))
  os.makedirs(outputRoot, exist_ok=True)
  timestamp = (datetime.datetime.now() if now is None else now).strftime("%Y-%m-%d-%H-%M-%S")
  while True:
    suffix = secrets.randbelow(10000) if randomSuffix is None else randomSuffix()
    runDirectory = os.path.join(outputRoot, f"{timestamp}-{suffix:04d}")
    try:
      os.mkdir(runDirectory)
    except FileExistsError:
      continue
    return runDirectory


def positiveInteger(value):
  value = int(value)
  if value < 1:
    raise argparse.ArgumentTypeError("must be at least 1")
  return value


def nonNegativeInteger(value):
  value = int(value)
  if value < 0:
    raise argparse.ArgumentTypeError("must be at least 0")
  return value


def searchConcurrency(value):
  value = int(value)
  if value < -1:
    raise argparse.ArgumentTypeError("must be -1 or greater")
  return value


def configure_mode(comp, mode):
  if mode == "build":
    comp.skipSearch()
  elif mode == "search":
    comp.skipIndex()


def normalize_and_validate_options(parser, args):
  if args.index_path is not None:
    args.index_path = os.path.abspath(os.path.expanduser(args.index_path))

  if args.index_path is not None and args.reindex:
    parser.error("--index-path cannot be combined with --reindex; an explicit path identifies one canonical index")


def parseRequestedTaskCategories(parser, args):
  value = args.queries.strip()
  if value == "":
    parser.error("--queries must not be empty")
  if value == "all":
    return None

  categories = []
  seen = set()
  for entry in value.split(","):
    category = entry.strip()
    if category == "":
      parser.error("--queries contains an empty category")
    if category == "all":
      parser.error("'all' is valid only as the entire --queries argument")
    if category not in seen:
      seen.add(category)
      categories.append(category)

  if args.mode == "build":
    parser.error("--queries applies only when search is enabled; use --queries all with --mode build")

  return tuple(categories)


def configureTaskCategories(comp, requestedTaskCategories):
  if requestedTaskCategories is None:
    return True

  for category in requestedTaskCategories:
    comp.addTaskPattern("^%s$" % re.escape(category))
  comp.setRequestedTaskCategories(requestedTaskCategories)
  return "PKLookup" in requestedTaskCategories


def configureExactPhases(parser, args):
  values = (args.warmup_repetitions, args.measured_repetitions, args.tasks_per_category)
  if not any(value is not None for value in values):
    if args.warmups is None:
      args.warmups = 20
    return None
  if not all(value is not None for value in values):
    parser.error("exact workload phases require --warmup-repetitions, --measured-repetitions, and --tasks-per-category")
  if args.warmups is not None:
    parser.error("--warmups cannot be combined with exact workload phase options")
  if args.mode == "build":
    if args.perf_control:
      parser.error("--perf-control applies only when search is enabled")
    parser.error("exact workload phases apply only when search is enabled")
  return values


def validatePerfControl(parser, args, exactPhases):
  if not args.perf_control:
    return
  if exactPhases is None:
    parser.error("--perf-control requires the complete exact workload phase configuration")
  if args.mode == "build":
    parser.error("--perf-control applies only when search is enabled")


def validateHardwareSummary(parser, args, exactPhases):
  if not args.hardware_summary:
    return
  if exactPhases is None:
    parser.error("--hardware-summary requires the complete exact workload phase configuration")
  if args.mode == "build":
    parser.error("--hardware-summary applies only when search is enabled")


def parsePerfEvents(parser, value, mode):
  if value is None:
    return None
  if mode == "build":
    parser.error("--perf-events applies only when search is enabled")
  events = []
  for entry in value.split(","):
    event = entry.strip()
    if event == "":
      parser.error("--perf-events contains an empty event name")
    events.append(event)
  return tuple(events)


def validateJVMOptions(parser, args):
  for argument in args.jvm_arg:
    if re.match(r"^-XX:\+Use.*GC$", argument):
      parser.error("GC selector JVM arguments must use --gc instead of --jvm-arg")


def validateKnnOptions(parser, args):
  if args.mode != "search":
    parser.error("--workload knn requires --mode search")
  required = (
    ("--knn-index-path", args.knn_index_path),
    ("--knn-docs", args.knn_docs),
    ("--knn-queries", args.knn_queries),
    ("--knn-doc-count", args.knn_doc_count),
    ("--knn-dim", args.knn_dim),
  )
  missing = [name for name, value in required if value is None]
  if missing:
    parser.error("--workload knn requires " + ", ".join(missing))
  args.knn_index_path = os.path.abspath(os.path.expanduser(args.knn_index_path))
  args.knn_docs = os.path.abspath(os.path.expanduser(args.knn_docs))
  args.knn_queries = os.path.abspath(os.path.expanduser(args.knn_queries))
  if not os.path.isdir(args.knn_index_path):
    parser.error("--knn-index-path must be an existing directory")
  for option, path in (("--knn-docs", args.knn_docs), ("--knn-queries", args.knn_queries)):
    if not os.path.isfile(path):
      parser.error(f"{option} must be an existing file")
  if args.reindex:
    parser.error("--workload knn search does not support --reindex")
  if args.hardware_summary:
    parser.error("--hardware-summary is implicit for --workload knn")
  if args.warmups is not None or any(value is not None for value in (args.warmup_repetitions, args.measured_repetitions, args.tasks_per_category)):
    parser.error("KnnGraphTester uses one warmup pass and one measured pass; normal-search repetition options do not apply to --workload knn")


def printConciseConfiguration(args, comp, index, requestedTaskCategories, perfEvents):
  indexPath = index.getPath() if hasattr(index, "getPath") else (args.index_path or "generated from benchmark configuration")
  defaultQueryConcurrency = getattr(getattr(competition, "constants", None), "SEARCH_NUM_CONCURRENT_QUERIES", "SEARCH_NUM_CONCURRENT_QUERIES")
  queryConcurrency = args.query_concurrency if args.query_concurrency is not None else defaultQueryConcurrency
  print("Search benchmark" if args.mode != "build" else "Index benchmark")
  print(f"  mode: {args.mode}")
  print(f"  source: {args.source}")
  print(f"  index: {indexPath}")
  print(f"  seed: {comp.randomSeed}")
  print(f"  JVM iterations: {args.iterations}")
  if args.mode == "build":
    print(f"  index threads: {args.index_threads}")
  if args.mode != "build":
    queries = "all" if requestedTaskCategories is None else ",".join(requestedTaskCategories)
    resolvedPerfEvents = getattr(getattr(competition, "benchUtil", None), "PERF_STATS", ("constants.PERF_STATS",)) if perfEvents is None else perfEvents
    print(f"  queries: {queries}")
    print(f"  query concurrency: {queryConcurrency}")
    print(f"  search concurrency: {args.search_concurrency}")
    if args.warmup_repetitions is None:
      print(f"  task repetitions: {args.warmups}")
      print("  exact phases: disabled")
    else:
      print(f"  warmup repetitions: {args.warmup_repetitions}")
      print(f"  measured repetitions: {args.measured_repetitions}")
      print(f"  tasks/category: {args.tasks_per_category}")
    print(f"  perf control: {'enabled' if args.perf_control else 'disabled'}")
    print(f"  perf events: {','.join(resolvedPerfEvents)}")
    if args.hardware_summary:
      print("  hardware summary: enabled")
    print(f"  profile: {args.profile}")
    print(f"  GC: {args.gc if args.gc is not None else 'existing Java command'}")
    if args.jvm_arg:
      print(f"  extra JVM arguments: {args.jvm_arg}")
  print()


# simple example that runs benchmark with WIKI_MEDIUM source and taks files
# Baseline here is ../lucene_baseline versus ../lucene_candidate
if __name__ == "__main__":
  parser = argparse.ArgumentParser(prog="Local Benchmark Run", description="Run a local benchmark on provided source dataset.")
  parser.add_argument("--workload", choices=("search", "knn"), default="search", help="Benchmark workload (default: search)")
  parser.add_argument("-s", "-source", "--source", help="Data source to run the benchmark on.")
  parser.add_argument(
    "--mode",
    choices=("both", "build", "search"),
    default="both",
    help="Benchmark execution mode: build indexes and search (both), build indexes only, or search existing indexes only (default: both)",
  )
  parser.add_argument(
    "--index-path",
    help="Exact canonical luceneutil index root to build or search (the complete benchmark-created directory, not only its inner index/ subdirectory)",
  )
  parser.add_argument("--index-threads", type=positiveInteger, default=1, help="Number of concurrent document indexing threads (default: 1)")
  parser.add_argument(
    "--queries",
    default="all",
    help="Query categories: all, one exact category, or a comma-separated list such as HighTerm,AndHighHigh,HighPhrase",
  )
  parser.add_argument(
    "--query-concurrency",
    type=positiveInteger,
    help="Number of simultaneous top-level independent query tasks (default: SEARCH_NUM_CONCURRENT_QUERIES)",
  )
  parser.add_argument(
    "-searchConcurrency",
    "--searchConcurrency",
    "--search-concurrency",
    dest="search_concurrency",
    default=-1,
    type=searchConcurrency,
    help="Lucene internal search workers per query: 0 disables concurrency, -1 uses all available cores (default: -1)",
  )
  parser.add_argument("-b", "--baseline", default=os.environ.get("BASELINE") or "lucene_baseline", help="Path to lucene repo to be used for baseline")
  parser.add_argument("-c", "--candidate", default=os.environ.get("CANDIDATE") or "lucene_candidate", help="Path to lucene repo to be used for candidate")
  parser.add_argument("-r", "--reindex", action="store_true", help="Reindex data for candidate run")
  parser.add_argument("-iterations", "--iterations", default=20, type=int, help="Number of JVM iterations (separate JVM processes, default: 20)")
  parser.add_argument("--seed", type=int, help="Fixed benchmark seed for reproducible task selection and ordering")
  parser.add_argument("-warmups", "--warmups", type=int, help="Legacy taskRepeatCount within each JVM (default: 20)")
  parser.add_argument("--warmup-repetitions", type=nonNegativeInteger, help="Exact warmup repetitions per selected base task")
  parser.add_argument("--measured-repetitions", type=positiveInteger, help="Exact measured repetitions per selected base task")
  parser.add_argument("--tasks-per-category", type=positiveInteger, help="Exact number of selected base tasks for each regular category")
  parser.add_argument(
    "--perf-control",
    action="store_true",
    help="Enable perf counters only for the exact measured phase; requires all exact workload phase options",
  )
  parser.add_argument(
    "--perf-events",
    help="Comma-separated perf stat events for this run (default: existing constants.PERF_STATS)",
  )
  parser.add_argument("--verbose", action="store_true", help="Print detailed benchmark diagnostics to the console")
  parser.add_argument("--jvm-arg", action="append", default=[], help="Additional JVM argument; repeat once per argv element")
  parser.add_argument(
    "--gc",
    choices=("parallel", "g1", "default"),
    help="Replace the existing ParallelGC default for search: parallel, g1, or the JVM default collector",
  )
  parser.add_argument("--profile", choices=("jfr", "none"), default="jfr", help="Search profiling mode (default: jfr)")
  parser.add_argument(
    "--hardware-summary",
    action="store_true",
    help="Record only measured count, elapsed time, and QPS; requires complete exact workload phases",
  )
  parser.add_argument(
    "--output-root",
    help="Root directory for per-invocation search artifacts (default: constants.LOGS_DIR)",
  )
  parser.add_argument("--knn-index-path", help="Existing KnnGraphTester index directory")
  parser.add_argument("--knn-docs", help="KNN document vector file used to build the existing index")
  parser.add_argument("--knn-queries", help="KNN query vector file")
  parser.add_argument("--knn-doc-count", type=positiveInteger, help="Number of vectors in the existing KNN index")
  parser.add_argument("--knn-dim", type=positiveInteger, help="Vector dimensions")
  parser.add_argument("--knn-top-k", type=positiveInteger, default=100, help="KNN top K (default: 100)")
  parser.add_argument("--knn-fanout", type=nonNegativeInteger, default=100, help="Additional KNN search fanout (default: 100)")
  parser.add_argument("--knn-query-start-index", type=nonNegativeInteger, default=0, help="First query vector ordinal (default: 0)")
  parser.add_argument("--knn-query-count", type=positiveInteger, default=100, help="Number of query vectors (default: 100)")
  parser.add_argument("--knn-query-concurrency", type=positiveInteger, default=1, help="Number of simultaneous independent KNN queries (default: 1)")
  parser.add_argument("--knn-search-threads", type=searchConcurrency, default=0, help="KNN intra-query search threads (default: 0)")
  parser.add_argument("--knn-quantization", choices=("float", "4bit-compressed"), default="float", help="Existing KNN index representation (default: float)")
  parser.add_argument("--knn-max-conn", type=positiveInteger, default=32, help="Existing HNSW maxConn (default: 32)")
  parser.add_argument("--knn-beam-width-index", type=positiveInteger, default=100, help="Existing HNSW beamWidthIndex (default: 100)")
  args = parser.parse_args()
  if args.workload == "knn":
    validateJVMOptions(parser, args)
    validateKnnOptions(parser, args)
    perfEvents = parsePerfEvents(parser, args.perf_events, args.mode)
    if args.perf_control:
      perfEvents = tuple(getattr(getattr(competition, "benchUtil", None), "PERF_STATS", ())) if perfEvents is None else perfEvents
    elif perfEvents is not None:
      parser.error("--perf-events requires --perf-control for --workload knn")
    else:
      perfEvents = ()
    outputRoot = args.output_root
    if outputRoot is None:
      outputRoot = getattr(getattr(competition, "constants", None), "LOGS_DIR", None)
    if outputRoot is None:
      parser.error("--workload knn requires --output-root when constants.LOGS_DIR is unavailable")
    runDirectory = createRunDirectory(outputRoot)
    print(f"Run directory: {runDirectory}")
    import knnHardwareBench

    config = knnHardwareBench.Config(
      indexPath=args.knn_index_path,
      docsPath=args.knn_docs,
      queriesPath=args.knn_queries,
      docCount=args.knn_doc_count,
      dim=args.knn_dim,
      topK=args.knn_top_k,
      fanout=args.knn_fanout,
      queryStartIndex=args.knn_query_start_index,
      queryCount=args.knn_query_count,
      queryConcurrency=args.knn_query_concurrency,
      searchThreads=args.knn_search_threads,
      quantization=args.knn_quantization,
      maxConn=args.knn_max_conn,
      beamWidthIndex=args.knn_beam_width_index,
      seed=args.seed,
      perfControl=args.perf_control,
      perfEvents=perfEvents,
      profile=args.profile,
      jvmArgs=tuple(args.jvm_arg),
      gc=args.gc,
      verbose=args.verbose,
    )
    print("KNN search benchmark")
    print(f"  index: {config.indexPath}")
    print(f"  queries: {config.queriesPath}")
    print(f"  query range: {config.queryStartIndex}..{config.queryStartIndex + config.queryCount - 1}")
    print(f"  query concurrency: {config.queryConcurrency}")
    print(f"  topK/fanout: {config.topK}/{config.fanout}")
    print(f"  search threads: {config.searchThreads}")
    print(f"  quantization: {config.quantization}")
    print(f"  seed: {config.seed if config.seed is not None else 'JVM-generated'}")
    print(f"  perf control: {'enabled' if config.perfControl else 'disabled'}")
    print(f"  profile: {config.profile}\n")
    knnHardwareBench.run(
      config,
      (("baseline", args.baseline), ("my_modified_version", args.candidate)),
      args.iterations,
      runDirectory,
    )
    sys.exit(0)
  normalize_and_validate_options(parser, args)
  requestedTaskCategories = parseRequestedTaskCategories(parser, args)
  exactPhases = configureExactPhases(parser, args)
  validatePerfControl(parser, args, exactPhases)
  validateHardwareSummary(parser, args, exactPhases)
  perfEvents = parsePerfEvents(parser, args.perf_events, args.mode)
  validateJVMOptions(parser, args)
  outputRoot = args.output_root
  if outputRoot is None:
    outputRoot = getattr(getattr(competition, "constants", None), "LOGS_DIR", None)
  runDirectory = createRunDirectory(outputRoot) if args.mode != "build" and outputRoot is not None else None
  if runDirectory is not None:
    print(f"Run directory: {runDirectory}")
  if args.verbose:
    print("Running benchmarks with the following args: %s" % args)

  sourceData = competition.sourceData(args.source)
  countsAreCorrect = args.search_concurrency != 0
  if exactPhases is None:
    comp = competition.Competition(
      verifyCounts=not countsAreCorrect, jvmCount=args.iterations, taskRepeatCount=args.warmups,
      randomSeed=args.seed, perfEvents=perfEvents, verbose=args.verbose, outputDir=runDirectory,
      jvmArgs=args.jvm_arg, gc=args.gc, profile=args.profile,
    )
  else:
    comp = competition.Competition(
      verifyCounts=not countsAreCorrect,
      jvmCount=args.iterations,
      taskCountPerCat=args.tasks_per_category,
      warmupTaskRepeatCount=args.warmup_repetitions,
      measuredTaskRepeatCount=args.measured_repetitions,
      randomSeed=args.seed,
      perfControl=args.perf_control,
      perfEvents=perfEvents,
      verbose=args.verbose,
      hardwareSummary=args.hardware_summary,
      outputDir=runDirectory,
      jvmArgs=args.jvm_arg,
      gc=args.gc,
      profile=args.profile,
    )
  configure_mode(comp, args.mode)
  includePK = configureTaskCategories(comp, requestedTaskCategories)

  index = comp.newIndex(
    args.baseline,
    sourceData,
    indexPath=args.index_path,
    numThreads=args.index_threads,
    addDVFields=True,
    useCMS=True,
    mergePolicy="TieredMergePolicy",
    facets=(
      ("taxonomy:Date", "Date"),
      ("taxonomy:Month", "Month"),
      ("taxonomy:DayOfYear", "DayOfYear"),
      ("sortedset:Date", "Date"),
      ("sortedset:Month", "Month"),
      ("sortedset:DayOfYear", "DayOfYear"),
      ("taxonomy:RandomLabel", "RandomLabel"),
      ("sortedset:RandomLabel", "RandomLabel"),
    ),
  )

  # create a competitor named baseline with sources in the ../trunk folder
  if args.query_concurrency is None:
    comp.competitor("baseline", args.baseline, index=index, searchConcurrency=args.search_concurrency, pk=includePK)
  else:
    comp.competitor(
      "baseline",
      args.baseline,
      index=index,
      numConcurrentQueries=args.query_concurrency,
      searchConcurrency=args.search_concurrency,
      pk=includePK,
    )

  # use the same index as baseline unless --reindex was passed.
  # create a competitor named my_modified_version (or provided candidate name) with sources in the ../patch folder
  # if --reindex flag is not used, luceneutil will automatically use the index from the base competitor for searching
  # while the codec that is used for running this competitor is taken from this competitor.
  candidate_index = index
  if args.reindex:
    candidate_index = comp.newIndex(
      args.candidate,
      sourceData,
      numThreads=args.index_threads,
      addDVFields=True,
      useCMS=True,
      mergePolicy="TieredMergePolicy",
      extraNamePart="candidate",
      facets=(
        ("taxonomy:Date", "Date"),
        ("taxonomy:Month", "Month"),
        ("taxonomy:DayOfYear", "DayOfYear"),
        ("sortedset:Date", "Date"),
        ("sortedset:Month", "Month"),
        ("sortedset:DayOfYear", "DayOfYear"),
        ("taxonomy:RandomLabel", "RandomLabel"),
        ("sortedset:RandomLabel", "RandomLabel"),
      ),
    )
  if args.query_concurrency is None:
    comp.competitor("my_modified_version", args.candidate, index=candidate_index, searchConcurrency=args.search_concurrency, pk=includePK)
  else:
    comp.competitor(
      "my_modified_version",
      args.candidate,
      index=candidate_index,
      numConcurrentQueries=args.query_concurrency,
      searchConcurrency=args.search_concurrency,
      pk=includePK,
    )

  if not args.verbose:
    printConciseConfiguration(args, comp, index, requestedTaskCategories, perfEvents)

  # start the benchmark - this can take long depending on your index and machines
  comp.benchmark("baseline_vs_patch")
