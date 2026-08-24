package perf;

/**
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.lucene.queryparser.classic.ParseException;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.TotalHits;
import org.apache.lucene.util.BytesRef;

import static perf.TaskParser.parseCategory;

// Serves up tasks from locally loaded list:
class LocalTaskSource implements TaskSource {
  static final class Workload {
    private final List<Task> prototypes;

    Workload(List<Task> prototypes) {
      this.prototypes = List.copyOf(prototypes);
    }

    LocalTaskSource newTaskSource(int taskRepeatCount, long phaseSeed, boolean groupByCat) {
      return newTaskSource(taskRepeatCount, phaseSeed, groupByCat, false);
    }

    LocalTaskSource newTaskSource(int taskRepeatCount, long phaseSeed, boolean groupByCat,
                                  boolean releaseTasksOnDispatch) {
      return new LocalTaskSource(prototypes, taskRepeatCount, new Random(phaseSeed), groupByCat,
                                 releaseTasksOnDispatch);
    }

    List<Task> getPrototypes() {
      return prototypes;
    }
  }

  private final List<Task> tasks;
  private final boolean releaseTasksOnDispatch;
  private final AtomicInteger nextTask = new AtomicInteger();
  private double pctNextPrint;
  private int taskCountNextPrint;

  public LocalTaskSource(IndexState indexState, String tasksFile, TaskParser taskParser,
                         Random staticRandom, Random random, int numTaskPerCat, int taskRepeatCount,
                         boolean doPKLookup, boolean groupByCat) throws IOException, ParseException {

    this(loadWorkload(indexState, tasksFile, taskParser, staticRandom, numTaskPerCat, doPKLookup, false).prototypes,
         taskRepeatCount, random, groupByCat, false);
  }

  static Workload loadWorkload(IndexState indexState, String tasksFile, TaskParser taskParser,
                               Random staticRandom, int numTaskPerCat, boolean doPKLookup,
                               boolean requireExactTasksPerCategory) throws IOException, ParseException {

    final List<Task> loadedTasks = loadTasks(tasksFile, taskParser);
    Collections.shuffle(loadedTasks, staticRandom);
    final List<Task> prunedTasks = pruneTasks(loadedTasks, numTaskPerCat, requireExactTasksPerCategory);

    // Add PK tasks
    //System.out.println("WARNING: skip PK tasks");
    if (doPKLookup) {
      final IndexSearcher searcher = indexState.mgr.acquire();
      final int maxDoc;
      try {
        maxDoc = searcher.getIndexReader().maxDoc();
      } finally {
        indexState.mgr.release(searcher);
      }

      final int numPKTasks = (int) Math.min(maxDoc/6000., numTaskPerCat);
      final Set<BytesRef> pkSeenIDs = new HashSet<BytesRef>();
      //final Set<BytesRef> pkWithTermStateSeenIDs = new HashSet<BytesRef>();
      //final Set<Integer> pkSeenIntIDs = new HashSet<Integer>();
      for(int idx=0;idx<numPKTasks;idx++) {
        prunedTasks.add(new BatchPKLookup(maxDoc, staticRandom, 4000, pkSeenIDs, idx));
        //prunedTasks.add(new PKLookupWithTermStateTask(maxDoc, staticRandom, 4000, pkWithTermStateSeenIDs, idx));
        //prunedTasks.add(new PointsPKLookupTask(maxDoc, staticRandom, 4000, pkSeenIntIDs, idx));
      }
      /*
      final Set<BytesRef> pkSeenSingleIDs = new HashSet<BytesRef>();
      for(int idx=0;idx<numPKTasks*100;idx++) {
        prunedTasks.add(new SinglePKLookupTask(maxDoc, staticRandom, pkSeenSingleIDs, idx));
      }
      */
    }
    return new Workload(prunedTasks);
  }

  private LocalTaskSource(List<Task> prototypes, int taskRepeatCount, Random random, boolean groupByCat,
                          boolean releaseTasksOnDispatch) {
    this.releaseTasksOnDispatch = releaseTasksOnDispatch;
    tasks = new ArrayList<>();
    if (groupByCat) {
      repeatTasksGrouped(prototypes, taskRepeatCount, random);
    } else {
      repeatTasksShuffled(prototypes, taskRepeatCount, random);
    }
    pctNextPrint = 5d;
    taskCountNextPrint = (int) ((pctNextPrint/100) * tasks.size());
    System.out.println("TASK LEN=" + tasks.size());
    if (tasks.size() == 0) {
      throw new RuntimeException("no tasks loaded");
    }
  }

  private void repeatTasksShuffled(List<Task> someTasks, int taskRepeatCount, Random random) {
    // Copy the pruned tasks multiple times, shuffling the order each time:
    final List<Task> orderedTasks = new ArrayList<>(someTasks);
    for(int iter = 0; iter < taskRepeatCount; iter++) {
      Collections.shuffle(orderedTasks, random);
      for(Task task : orderedTasks) {
        tasks.add(task.clone());
      }
    }
  }

  private void repeatTasksGrouped(List<Task> someTasks, int taskRepeatCount, Random random) {
    Map<String, List<Task>> tasksByCategory = new HashMap<>();
    for (Task task : someTasks) {
      String category = task.getCategory();
      tasksByCategory.computeIfAbsent(category, c -> new ArrayList<>()).add(task);
    }
    for (String category : tasksByCategory.keySet()) {
      List<Task> categoryTasks = tasksByCategory.get(category);
      repeatTasksShuffled(categoryTasks, taskRepeatCount, random);
    }
  }

  @Override
  public List<Task> getAllTasks() {
    return tasks;
  }

  int getTaskCount() {
    return tasks.size();
  }

  static List<Task> pruneTasks(List<Task> tasks, int numTaskPerCat, boolean requireExactTasksPerCategory) {
    final Map<String,Integer> catCounts = new HashMap<String,Integer>();
    final List<Task> newTasks = new ArrayList<Task>();
    for(Task task : tasks) {
      final String cat = task.getCategory();
      Integer v = catCounts.get(cat);
      int catCount;
      if (v == null) {
        catCount = 0;
      } else {
        catCount = v.intValue();
      }

      if (catCount >= numTaskPerCat) {
        // System.out.println("skip task cat=" + cat);
        continue;
      }
      catCount++;
      catCounts.put(cat, catCount);
      newTasks.add(task);
    }

    if (requireExactTasksPerCategory) {
      for (Map.Entry<String,Integer> entry : catCounts.entrySet()) {
        if (entry.getValue() < numTaskPerCat) {
          throw new IllegalArgumentException("exact phase requested " + numTaskPerCat + " tasks for category " + entry.getKey() +
                                             " but task file contains only " + entry.getValue());
        }
      }
    }

    return newTasks;
  }

  @Override
  public Task nextTask() {
    final int next = nextTask.getAndIncrement();
    if (next == taskCountNextPrint) {
      System.out.println(pctNextPrint + "%... (" + next + " of " + tasks.size() + ")");
      pctNextPrint += 5;
      // NOTE: some risk of thread non-safety causing progress to stop printing entirely!  But this should
      // only happen on very fast runs where we don't need to see progress anyways:
      taskCountNextPrint = (int) ((pctNextPrint/100) * tasks.size());
    }
    if (next >= tasks.size()) {
      return null;
    }
    final Task task = tasks.get(next);
    if (releaseTasksOnDispatch) {
      // nextTask assigns every slot to at most one caller, so releasing this
      // source-owned reference cannot affect ordering or another worker.
      tasks.set(next, null);
    }
    return task;
  }

  @Override
  public void taskDone(Task task, long queueTimeNS, TotalHits toalHitCount) {
  }

  static List<Task> loadTasks(String filePath, TaskParser taskParser) throws IOException, ParseException {
    final List<Task> tasks = new ArrayList<Task>();
    final BufferedReader taskFile = new BufferedReader(new InputStreamReader(new FileInputStream(filePath), "UTF-8"), 16384);
    while (true) {
      String line = taskFile.readLine();
      if (line == null) {
        break;
      }
      line = line.trim();
      if (line.indexOf("#") == 0) {
        // Ignore comment lines
        continue;
      }
      if (line.length() == 0) {
        // Ignore blank lines
        continue;
      }

      // Only parse the category here, will parse to specific task when searching
      tasks.add(taskParser.firstPassParse(line));
    }
    taskFile.close();
    return tasks;
  }
  
}
