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
import os
import re

import competition


def positiveInteger(value):
  value = int(value)
  if value < 1:
    raise argparse.ArgumentTypeError("must be at least 1")
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


# simple example that runs benchmark with WIKI_MEDIUM source and taks files
# Baseline here is ../lucene_baseline versus ../lucene_candidate
if __name__ == "__main__":
  parser = argparse.ArgumentParser(prog="Local Benchmark Run", description="Run a local benchmark on provided source dataset.")
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
  parser.add_argument("-warmups", "--warmups", default=20, type=int, help="Number of times each query runs within a single JVM for warmup (default: 20)")
  args = parser.parse_args()
  normalize_and_validate_options(parser, args)
  requestedTaskCategories = parseRequestedTaskCategories(parser, args)
  print("Running benchmarks with the following args: %s" % args)

  sourceData = competition.sourceData(args.source)
  countsAreCorrect = args.search_concurrency != 0
  comp = competition.Competition(verifyCounts=not countsAreCorrect, jvmCount=args.iterations, taskRepeatCount=args.warmups)
  configure_mode(comp, args.mode)
  includePK = configureTaskCategories(comp, requestedTaskCategories)

  index = comp.newIndex(
    args.baseline,
    sourceData,
    indexPath=args.index_path,
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

  # start the benchmark - this can take long depending on your index and machines
  comp.benchmark("baseline_vs_patch")
