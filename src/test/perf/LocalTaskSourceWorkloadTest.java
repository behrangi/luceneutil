package perf;

import java.io.IOException;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.List;

final class LocalTaskSourceWorkloadTest {
  private static final long WARMUP_SEED = 17L;
  private static final long MEASURED_SEED = 29L;

  public static void main(String[] args) throws Exception {
    testExactCountsFreshObjectsAndPrototypePreservation();
    testMeasuredOrderDoesNotDependOnWarmupRepetitions();
    testZeroWarmupStillAllowsMeasuredExecution();
    testPositiveRepetitionsRejectZeroPrototypes();
    testExactTasksPerCategoryRejectsInsufficientTasks();
  }

  private static void testExactCountsFreshObjectsAndPrototypePreservation() throws Exception {
    List<Task> prototypes = prototypes();
    LocalTaskSource.Workload workload = new LocalTaskSource.Workload(prototypes);
    LocalTaskSource warmup = workload.newTaskSource(3, WARMUP_SEED, false);
    LocalTaskSource measured = workload.newTaskSource(5, MEASURED_SEED, false);

    assertEquals(6, warmup.getAllTasks().size(), "warmup task count");
    assertEquals(10, measured.getAllTasks().size(), "measured task count");
    assertNoSharedIdentity(warmup.getAllTasks(), measured.getAllTasks());
    assertNoSharedIdentity(workload.getPrototypes(), warmup.getAllTasks());
    assertNoSharedIdentity(workload.getPrototypes(), measured.getAllTasks());

    execute(warmup.getAllTasks());
    execute(measured.getAllTasks());
    for (Task prototype : workload.getPrototypes()) {
      assertEquals(0, ((FakeTask) prototype).executionCount, "canonical prototype execution count");
    }
  }

  private static void testMeasuredOrderDoesNotDependOnWarmupRepetitions() throws Exception {
    LocalTaskSource.Workload workload = new LocalTaskSource.Workload(prototypes());

    LocalTaskSource warmupOnce = workload.newTaskSource(1, WARMUP_SEED, false);
    execute(warmupOnce.getAllTasks());
    LocalTaskSource measuredAfterOneWarmup = workload.newTaskSource(5, MEASURED_SEED, false);

    LocalTaskSource warmupTwentyTimes = workload.newTaskSource(20, WARMUP_SEED, false);
    execute(warmupTwentyTimes.getAllTasks());
    LocalTaskSource measuredAfterTwentyWarmups = workload.newTaskSource(5, MEASURED_SEED, false);

    assertEquals(taskIdentities(measuredAfterOneWarmup), taskIdentities(measuredAfterTwentyWarmups),
                 "measured sequence must not depend on warmup repetitions");
  }

  private static void testZeroWarmupStillAllowsMeasuredExecution() throws Exception {
    LocalTaskSource.Workload workload = new LocalTaskSource.Workload(prototypes());
    LocalTaskSource measured = workload.newTaskSource(5, MEASURED_SEED, false);
    execute(measured.getAllTasks());

    assertEquals(10, measured.getAllTasks().size(), "measured task count after zero warmup");
  }

  private static void testPositiveRepetitionsRejectZeroPrototypes() {
    LocalTaskSource.Workload workload = new LocalTaskSource.Workload(List.of());
    try {
      workload.newTaskSource(1, MEASURED_SEED, false);
      throw new AssertionError("expected positive-repeat empty workload rejection");
    } catch (RuntimeException expected) {
      assertEquals("no tasks loaded", expected.getMessage(), "empty workload validation message");
    }
  }

  private static void testExactTasksPerCategoryRejectsInsufficientTasks() {
    try {
      LocalTaskSource.pruneTasks(prototypes(), 3, true);
      throw new AssertionError("expected exact tasks-per-category validation failure");
    } catch (IllegalArgumentException expected) {
      if (expected.getMessage().contains("task file contains only 2") == false) {
        throw new AssertionError("unexpected validation message: " + expected.getMessage());
      }
    }
  }

  private static List<Task> prototypes() {
    return List.of(new FakeTask("one", "HighTerm"), new FakeTask("two", "HighTerm"));
  }

  private static void execute(List<Task> tasks) throws IOException {
    for (Task task : tasks) {
      task.go(null, null);
    }
  }

  private static List<String> taskIdentities(LocalTaskSource source) {
    List<String> identities = new ArrayList<>();
    for (Task task : source.getAllTasks()) {
      identities.add(((FakeTask) task).identity);
    }
    return identities;
  }

  private static void assertNoSharedIdentity(List<Task> first, List<Task> second) {
    for (Task firstTask : first) {
      for (Task secondTask : second) {
        if (firstTask == secondTask) {
          throw new AssertionError("task object was reused across prototype or phase lists");
        }
      }
    }
  }

  private static void assertEquals(Object expected, Object actual, String message) {
    if (expected.equals(actual) == false) {
      throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
    }
  }

  private static final class FakeTask extends Task {
    private final String identity;
    private final String category;
    private int executionCount;

    FakeTask(String identity, String category) {
      this.identity = identity;
      this.category = category;
    }

    @Override
    public void go(IndexState state, TaskParser taskParser) {
      executionCount++;
    }

    @Override
    public String getCategory() {
      return category;
    }

    @Override
    public Task clone() {
      return new FakeTask(identity, category);
    }

    @Override
    public long checksum() {
      return executionCount;
    }

    @Override
    public void printResults(PrintStream out, IndexState state) {
    }
  }
}
