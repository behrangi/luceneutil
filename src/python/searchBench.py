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

import os
import random
import re
import sys

import benchUtil
import common
import constants

PYTHON_MAJOR_VER = sys.version_info.major

osName = common.osName


def parseTaskCategory(line):
  i = line.find(":")
  if i == -1:
    return None
  return line[:i]


def readTaskCategories(tasksFile):
  categories = set()
  with open(tasksFile, encoding="utf-8") as f:
    for line in f:
      category = parseTaskCategory(line)
      if category is not None:
        categories.add(category)
  return categories


def commonTasksFile(base, challenger):
  tasksFile = base.tasksFile
  if challenger.tasksFile != tasksFile:
    raise RuntimeError("inconsistent taskFile %s vs %s" % (tasksFile, challenger.tasksFile))
  return tasksFile


def validateTaskCategories(requestedTaskCategories, tasksFile):
  if requestedTaskCategories is None:
    return

  availableCategories = readTaskCategories(tasksFile)
  availableCategories.add("PKLookup")
  unknownCategories = [category for category in requestedTaskCategories if category not in availableCategories]
  if unknownCategories:
    raise RuntimeError(
      "unknown query categories: %s (available categories: %s)" % (", ".join(unknownCategories), ", ".join(sorted(availableCategories)))
    )


def filterTasksFile(competitors, tasksFile, newTasksFile, taskPatterns):
  pos, neg = taskPatterns
  posPatterns = None if pos is None else [re.compile(pattern) for pattern in pos]
  negPatterns = None if neg is None else [re.compile(pattern) for pattern in neg]

  with open(tasksFile, encoding="utf-8") as f, open(newTasksFile, "wb") as fOut:
    for line in f:
      category = parseTaskCategory(line)
      if category is not None:
        if posPatterns is not None and not any(pattern.search(category) is not None for pattern in posPatterns):
          continue
        if negPatterns is not None and any(pattern.search(category) is not None for pattern in negPatterns):
          continue
      fOut.write(line.encode("utf-8"))

  for competitor in competitors:
    competitor.tasksFile = newTasksFile


def run(
  id,
  base,
  challenger,
  coldRun=False,
  doCharts=False,
  search=False,
  index=False,
  verifyScores=True,
  verifyCounts=True,
  taskPatterns=None,
  randomSeed=None,
  requireOverlap=1.0,
  skipReport=False,
  requestedTaskCategories=None,
):
  competitors = [challenger, base]
  verbose = getattr(base.competition, "verbose", False)

  if randomSeed is None:
    raise RuntimeError("missing randomSeed")

  if not search:
    search = "-search" in sys.argv

  if not index:
    index = "-index" in sys.argv

  if search:
    tasksFile = commonTasksFile(base, challenger)
    validateTaskCategories(requestedTaskCategories, tasksFile)

  # verifyScores = False
  r = benchUtil.RunAlgs(constants.JAVA_COMMAND, verifyScores, verifyCounts, verbose=verbose)
  if "-noc" not in sys.argv:
    if verbose:
      print()
      print("Compile:")
    for c in competitors:
      r.compile(c)
  sum = search or "-sum" in sys.argv

  if index:
    seen = set()
    indexSegCount = None
    indexCommit = None
    p = False
    for c in competitors:
      if c.index not in seen:
        if not p:
          print()
          print("Create indices:")
          p = True
        seen.add(c.index)
        r.makeIndex(id, c.index, doCharts)
        segCount = benchUtil.getSegmentCount(c.index.getPath())
        if indexSegCount is None:
          indexSegCount = segCount
          indexCommit = c.commitPoint
        elif indexCommit == c.commitPoint and indexSegCount != segCount:
          raise RuntimeError("segment counts differ across indices: %s vs %s" % (indexSegCount, segCount))

  logUpto = 0

  if search:
    if taskPatterns != (None, None):
      pos, neg = taskPatterns
      if verbose and pos is None:
        if neg is None:
          print("    tasks file: %s" % tasksFile)
        else:
          print("    tasks file: NOT %s from %s" % (",".join(neg), tasksFile))
      elif verbose and neg is None:
        print("    tasks file: %s from %s" % (",".join(pos), tasksFile))
      elif verbose:
        print("    tasks file: %s, NOT %s from %s" % (",".join(pos), ",".join(neg), tasksFile))
      newTasksFile = "%s/%s.tasks" % (constants.BENCH_BASE_DIR, os.getpid())
      filterTasksFile(competitors, tasksFile, newTasksFile, taskPatterns)

    else:
      if verbose:
        print("    tasks file: %s" % tasksFile)
      newTasksFile = None

    try:
      results = {}

      if constants.JAVA_COMMAND.find(" -ea") != -1:
        print("WARNING: assertions are enabled" if not verbose else "WARNING: *** assertions are enabled *** JAVA_COMMAND=%s" % constants.JAVA_COMMAND)

      if verbose:
        print()
        print("Search:")

      taskFiles = {}

      rand = random.Random(randomSeed)
      staticSeed = rand.randint(-10000000, 1000000)

      # Remove old log files:
      for c in competitors:
        for fileName in r.getSearchLogFiles(id, c):
          if os.path.exists(fileName):
            os.remove(fileName)

      for iter in range(base.competition.jvmCount):
        if verbose:
          print("  iter %d" % iter)

        seed = rand.randint(-10000000, 1000000)

        # Change which competitor runs first on every iteration to avoid
        # biasing results based on which competitors ran first or last.
        rotation_index = iter % len(competitors)
        rotated_competitors = competitors[rotation_index:] + competitors[:rotation_index]
        for c in rotated_competitors:
          if verbose:
            print("    %s:" % c.name)
          else:
            print(f"[{iter + 1}/{base.competition.jvmCount}] {c.name}")
          logFile = r.runSimpleSearchBench(iter, id, c, coldRun, seed, staticSeed, filter=None, taskPatterns=taskPatterns)
          results.setdefault(c, []).append(logFile)

        if verbose:
          print()
          print("Report after iter %d:" % iter)
        # print '  results: %s' % results
        reportWriter = sys.stdout.write if verbose else lambda unused_text: None
        details, cmpDiffs, cmpHeap = r.simpleReport(results[base], results[challenger], "-jira" in sys.argv, "-html" in sys.argv, cmpDesc=challenger.name, baseDesc=base.name, writer=reportWriter)
        if cmpDiffs is not None:
          if cmpDiffs[1]:
            raise RuntimeError("errors occurred: %s" % str(cmpDiffs))
          if cmpDiffs[2] < requireOverlap:
            raise RuntimeError("results differ: %s" % str(cmpDiffs))

    finally:
      if newTasksFile is not None and os.path.exists(newTasksFile):
        os.remove(newTasksFile)

    # TODO: maybe print this after each iter, not just in the end, for the impatient/progressive?
    if verbose:
      for mode in "cpu", "heap":
        for c in competitors:
          print(f"\n{mode.upper()} merged search profile for {c.name}:")
          print(c.getAggregateProfilerResult(id, mode, stackSize=12)[0][1])

  elif not skipReport:
    results = {}
    for c in competitors:
      results[c] = r.getSearchLogFiles(id, c)

    details, cmpDiffs, cmpHeap = r.simpleReport(results[base], results[challenger], "-jira" in sys.argv, "-html" in sys.argv, cmpDesc=challenger.name, baseDesc=base.name)  # noqa: RUF059
    if cmpDiffs is not None:
      raise RuntimeError("results differ: %s" % str(cmpDiffs))
