# Luceneutil: Lucene benchmarking utilities

![Benchmarking Lucene Duke -- thank you @mocobeta!](/Benchmarking-Duke-from-Tomoko.png)

### Setting up luceneutil

First, pick a root directory, under which luceneutil will be checked out,
datasets exist, indices are built, Lucene source code is checked out,
etc.. We'll refer to this directory as `$LUCENE_BENCH_HOME` here.

```
# 1. checkout luceneutil:
# Choose a suitable directory, e.g. ~/Projects/lucene/benchmarks.
mkdir $LUCENE_BENCH_HOME && cd $LUCENE_BENCH_HOME
git clone https://github.com/mikemccand/luceneutil.git util

# 2. Run the initial setup script
cd util
python src/python/initial_setup.py -download

# you can run with -h option for help
python src/python/initial_setup.py -h
```
  
In the second step, the setup procedure creates all necessary directories in the clones parent directory and downloads
datasets to run the benchmarks on. By default, it downloads a 6 GB compressed Wikipedia line doc file, and a 13 GB vectors
file from Apache mirrors. If you don't want to download the large data files,
just remove the `-download` flag from the commandline.

After the download has completed, extract the lzma file in `$LUCENE_BENCH_HOME/data`. You can do this using the `xz` tool,
or the `lmza` tool, or any other tool of your choice. For example:
```bash
cd $LUCENE_BENCH_HOME/data
# using xz
xz -d enwiki-20120502-lines-1k-fixed-utf8-with-random-label.txt.lzma
# using lmza
lzma -d enwiki-20120502-lines-1k-fixed-utf8-with-random-label.txt.lzma
```

### (Optional, for development) set up IntelliJ
Should be able to open by IntelliJ automatically. The gradle will write a local configuration file `gradle.properties` in
which you can configure your local lucene repository so that intellij will use it as external library and code suggestion
will work. Also because the compilation is looking for jar so you have to build your lucene repo (run `./gradlew jar`) manually if you haven't 
done so.
Note the gradle build will NOT be able to compile the whole project because
some codes do have errors so we still need to filter which files to compile (see competitions.py). So you still
need to follow the rest procedure.

### Preparing the benchmark candidates

The benchmark compares a baseline version of Lucene to a patched one. Therefore we need two checkouts of Lucene, for example:

* `$LUCENE_BENCH_HOME/lucene_baseline`: contains a complete git clone of Lucene, this is the baseline for comparison
* `$LUCENE_BENCH_HOME/lucene_candidate`: contains a complete git clone of Lucene with some change applied that should be benchmarked against the baseline.

The main branch of Lucene can be checked out with

```
cd $LUCENE_BENCH_HOME
git clone https://github.com/apache/lucene.git lucene_baseline
```

Adjust the command accordingly for `lucene_candidate`.

### Running a first benchmark

`initial_setup.py` has created two files: `localconstants.py`, and `localrun.py` in `$LUCENE_BENCH_HOME/util/src/python/`. 

The file `localconstants.py` should be used to override any existing constants in `constants.py`, for example if you want to change the Java commandline used to run benchmarks. To run an initial benchmark you don't need to modify this file.

Now you can start editing `localrun.py` to define your comparison, at the
bottom near its `__main__`:

This file is a copy of `example.py` and should be used to define your
comparisons. You don't have to build 2 separate indexes; you can make
one and pass it to the two different competitors if you are only benching
some code difference but not a file format change.

To run the benchmark you first test like this:

```
cd $LUCENE_BENCH_HOME/util
python src/python/localrun.py -source wikimedium10k
```

Then once you confirm that everything works, use the `wikimediumall` corpus for all subsequent runs.
Using this much much larger corpus (33+ million docs) is necessary to draw conclusions from your benchmark results.
```
python src/python/localrun.py -source wikimediumall
```

If you get ClassNotFound exceptions, your Lucene checkouts may need to be rebuilt. Run `./gradlew jar` in both `lucene_candidate/` and `lucene_baseline/` dirs.

If your benchmark fails with "facetDim Date was not indexed" or similar, try adding

    facets = (('taxonomy:Date', 'Date'),('sortedset:Month', 'Month'),('sortedset:DayOfYear', 'DayOfYear'))
    index = comp.newIndex('lucene_baseline', sourceData, facets=facets, indexSort='dayOfYearNumericDV:long')

in `localrun.py`, and use that index in your benchmarks.

### Additional Run Options
You can also make the benchmark use baseline or candidate repository that exists outside of the directory structure above. 
Simply use `-b <Baseline repo path>` or `-c <Candidate repo path>` as shown below:
```bash
python src/python/localrun.py -source wikimediumall -b /Users/vigyas/repos/lucene -c /Users/vigyas/forks/lucene
```

While benchmarking an indexing side change, you might want to recreate the index for your candidate run. Use the `-r / --reindex` arg as follows:
```bash
python src/python/localrun.py -source wikimediumall -r
```

### Execution modes

By default, a local benchmark builds any missing indexes and then runs the search benchmark. The same behavior can be selected explicitly with `--mode both`:

```bash
python src/python/localrun.py -source wikimediumall --mode both
```

Use `--mode build` to build any missing indexes without running the search benchmark:

```bash
python src/python/localrun.py -source wikimediumall --mode build
```

Use `--mode search` to search existing indexes without invoking index creation:

```bash
python src/python/localrun.py -source wikimediumall --mode search
```

Search mode requires the indexes identified by the benchmark configuration to already exist.

### Explicit index path

Use `--index-path` to build or search one canonical index at an exact location instead of using the path generated from the benchmark configuration:

```bash
python src/python/localrun.py -source wikimediumall --mode build --index-path /data/lucene-index
python src/python/localrun.py -source wikimediumall --mode search --index-path /data/lucene-index
```

The path identifies the complete luceneutil index root created by the benchmark, not only its inner Lucene `index/` subdirectory. When transferring a canonical index to another system, copy the complete directory, including any index, facet, taxonomy, or related benchmark files beneath it.

User-supplied paths are expanded with `expanduser` and converted to absolute paths before benchmark configuration. Both competitors use the same canonical index.

- In `--mode search`, the path must be an existing directory and index creation is not invoked.
- In `--mode build`, the path must not exist. An existing path is never deleted, overwritten, or silently reused.
- In `--mode both`, an absent path is built and an existing directory is reused.

Python does not inspect Lucene index contents; Lucene determines whether an existing directory contains a valid usable index. An explicit canonical index cannot be combined with `--reindex`, which creates a separate candidate index in the ordinary A/B workflow.

### Query category selection

The default `--queries all` preserves the complete existing search workload, including the existing independent synthetic primary-key lookup workload. Select one exact category or a comma-separated list with `--queries`:

```bash
python src/python/localrun.py -source wikimediumall --queries all
python src/python/localrun.py -source wikimediumall --queries HighTerm
python src/python/localrun.py -source wikimediumall --queries HighTerm,AndHighHigh,HighPhrase
python src/python/localrun.py -source wikimediumall --queries PKLookup
python src/python/localrun.py -source wikimediumall --queries HighTerm,PKLookup
```

Category names are exact, case-sensitive literals. Whitespace around comma-separated names is ignored, and duplicate names retain their first occurrence. Empty and unknown category names are rejected.

`PKLookup` is generated independently by luceneutil and is not tied to a preceding search result. Explicit regular-only selections disable implicit PK lookup. Listing `PKLookup` enables the existing synthetic PK workload; selecting only `PKLookup` filters out every regular task category. For indexes smaller than 6,000 documents, the existing PK generator may produce no PK tasks.

`--mode build` accepts only `--queries all`, because query selection applies only when search is enabled. Build-only mode does not inspect or filter the search task file.

### Search concurrency controls

Two independent forms of search concurrency can be configured explicitly:

```bash
python src/python/localrun.py -source wikimediumall --query-concurrency 4 --search-concurrency 0
```

`--query-concurrency` controls how many independent top-level query tasks are in flight and must be at least 1. When omitted, the existing `SEARCH_NUM_CONCURRENT_QUERIES` default is preserved. `--search-concurrency` controls Lucene's internal workers for each individual search; `0` disables internal search concurrency and `-1` retains the existing use-all-available-cores behavior. The previous `--searchConcurrency` spelling remains accepted as an alias.

These options change only scheduling and parallelism. They do not change query selection, PK lookup enablement, task repetitions, tasks per category, JVM iterations, the selected index, or the total logical workload.

### Exact warmup and measured workloads

Hardware-characterization runs can define two finite execution phases explicitly:

```bash
python src/python/localrun.py -source wikimediumall --queries HighTerm \
  --warmup-repetitions 3 --measured-repetitions 5 --tasks-per-category 2
```

All three exact-phase options are required together. Warmup repetitions may be zero; measured repetitions and tasks per regular category must be at least one. Each selected regular category must contain at least the requested number of task definitions or the run fails. The example executes 6 warmup and 10 measured `HighTerm` tasks per JVM.

Warmup and measurement use the same selected base tasks, PK setting, index, and concurrency. They use fresh Task instances and independent deterministic ordering, so changing the warmup repetition count does not change the measured workload. Warmup results are discarded; only measured tasks are verified and reported. Exact mode bypasses Java's legacy time-based warmup and measures throughput over the complete finite measured phase.

Synthetic `PKLookup` remains independent. Its base batch count retains the existing `min(floor(maxDoc / 6000), tasks-per-category)` rule, and that base workload is repeated separately for warmup and measurement.

When none of these options is supplied, historical `--warmups`/`taskRepeatCount` behavior remains unchanged. Explicit `--warmups` cannot be combined with exact-phase options. Exact phases currently require a local finite task file; remote task sources are rejected.

Add `--perf-control` to an exact-phase search run to start `perf stat` with counters disabled, enable them only after warmup has completed, and disable them immediately after all measured workers finish. The benchmark waits for perf's acknowledgement at both boundaries; a control or acknowledgement failure aborts the run rather than falling back to whole-JVM measurement. This option is Linux-only, requires all three exact-phase options, and is not valid in build-only mode. Exact phases without `--perf-control` retain their normal Patch 5 behavior. Perf control does not alter event selection.

Select perf events for an individual run with `--perf-events`, for example `--perf-events cycles,instructions,stall_backend_mem,ll_cache_miss_rd`. The supplied comma-separated list replaces `constants.PERF_STATS` for that run; surrounding whitespace is removed while order and duplicate entries are preserved. Empty event names are rejected. When the option is omitted, the existing event list is unchanged. Event selection works independently with legacy whole-process perf execution and with `--perf-control`.

Console output is concise by default. It shows the effective benchmark configuration, each competitor/JVM iteration, exact-phase lifecycle markers, measured elapsed time, QPS, CPU use, and log paths. Add `--verbose` to retain detailed commands, setup diagnostics, per-iteration reports, and merged JFR profile presentation. Concise mode still captures raw subprocess output and the exact executed command in the run's `.stdout` log; failures always show the exit status, log path, and a useful output tail. JFR collection is unchanged in both modes.

For large hardware-characterization workloads, add `--hardware-summary` to a complete exact-phase search configuration. This retains the exact workload and perf-control boundaries but records only the completed measured-task count, measured elapsed time, QPS, and CPU use. It skips per-query result serialization, hit comparison, latency percentiles, and `out.png` generation. The option is not valid for legacy or build-only runs; omitting it preserves detailed result reporting unchanged.

Search invocations launched through `example.py` create one unique directory beneath `--output-root` (default: `constants.LOGS_DIR`). Its filesystem-safe ID has the form `YYYY-MM-DD-HH-MM-SS-RANDOM`. Each competitor and JVM iteration receives its own directory containing `result.log`, `process.log`, and `profile.jfr`; when perf is available, its delimiter-separated raw counter output is written separately to `perf.stat`. Organized exact `--hardware-summary` runs also atomically publish a versioned `result.json` containing the resolved configuration, authoritative measured summary, raw perf event values/status, and mechanically derived metrics. The resolved absolute run directory is printed when execution begins.

For quick patch testing, you can control the number of JVM iterations and query repetitions to speed up the benchmark:
```bash
# Quick test: 5 JVM iterations, 10 query repetitions per JVM
python src/python/localrun.py -source wikimediumall -iterations 5 -warmups 10

# Full benchmark (default): 20 JVM iterations, 20 query repetitions per JVM
python src/python/localrun.py -source wikimediumall -iterations 20 -warmups 20
```

**Note:** The `-iterations` parameter controls how many separate JVM processes are launched (default: 20), and `-warmups` controls how many times each query runs within a single JVM (default: 20). Running with default settings (20×20) provides the most statistically reliable results and recommended for benchmarks testing to get a complete picture. For quick patch validation, reducing these values significantly speeds up testing.

For details on all the available options, use the `-h` or `--help` parameter.

### Useful `localconstants.py` overrides

Any variable in `constants.py` can be overridden in `localconstants.py`. Some common ones:

```python
# Use multiple indexing threads (default: 1)
INDEX_NUM_THREADS = 8

# Use the binary line docs format for faster document parsing.
# Generate it with: python3 -u src/python/buildBinaryLineDocs.py <input.txt> <output.bin>
WIKI_MEDIUM_DOCS_LINE_FILE = '%s/data/enwiki-20120502-lines-1k-fixed-utf8-with-random-label.bin' % BASE_DIR

# Override the Java version and commandline
import os
os.environ["JAVA_HOME"] = "/path/to/jdk"
# add jfr and other JDK tools to PATH
os.environ["PATH"] = os.environ["JAVA_HOME"] + "/bin:" + os.environ.get("PATH", "")
java_home = os.environ["JAVA_HOME"]
_java_bin = java_home + "/bin/"
JAVA_EXE = f"{_java_bin}java"
JAVAC_EXE = f"{_java_bin}javac"
JAVA_COMMAND = "%s -server -Xms8g -Xmx8g --add-modules jdk.incubator.vector -XX:+HeapDumpOnOutOfMemoryError -XX:+UseParallelGC" % JAVA_EXE
```

# Running the geo benchmark

This one is different and self-contained. Read the command-line examples at the top of src/main/perf/IndexAndSearchOpenStreetMaps.java

# Creating line doc file from an arbitrary Wikimedia dump data

You can create your own line doc file from an arbitrary Wikimedia dump by following steps.  Note that the `src/python/createJapaneseWikipediaLineDocsFile.py` helper tool does these steps:

1. Download Wikimedia dump (XML) from https://dumps.wikimedia.org/ and decompress it on `$YOUR_DATA_DIR`.

    e.g.:
    ```
    bunzip2 -d /data/jawiki/jawiki-20200620-pages-articles-multistream.xml.bz2
    ```

2. Run `src/python/wikiXMLToText.py` to extract attributes such as title and timestamp from the XML dump.

    e.g.:
    ```
    python src/python/wikiXMLToText.py /data/jawiki/jawiki-20200620-pages-articles-multistream.xml /data/jawiki/jawiki-20200620-text.txt
    ```

3. Run `src/python/WikipediaExtractor.py` to extract cleaned body text from the XML dump. This may take long time!

    e.g.:
    ```
    cat /data/jawiki/jawiki-20200620-pages-articles-multistream.xml | python -u src/python/WikipediaExtractor.py -b102400m -o /data/jawiki
    ```

4a. Combine the outputs of 2. and 3. by running `src/python/combineWikiFiles.py`.

    e.g.:
    ```
    python src/python/combineWikiFiles.py /data/jawiki/jawiki-20200620-text.txt /data/jawiki/AA/wiki_00 /data/jawiki/jawiki-20200620-lines.txt
    ```

4b. (Optional) If you want to strip all but the last three columns from the combined file, pass the `-only-three-columns` to combineWikiFiles.py:

    e.g.:
    ```
    python src/python/combineWikiFiles.py /data/jawiki/jawiki-20200620-text.txt /data/jawiki/AA/wiki_00 /data/jawiki/jawiki-20200620-lines.txt -only-three-columns
    ```

    Alternatively, use the Unix `cut` tool:

    ```
    # extract titie, timestamp and body text
    cat /data/jawiki/jawiki-20200620-lines.txt | cut -f1,2,3
    ```
# Running the KNN benchmark

Some knn-related tasks are included in the main benchmarks. If you specifically want to test
KNN/HNSW there is a script dedicated to that in src/python/knnPerfTest.py which has instructions on
how to run it in its comments.

## Testing with higher dimension vectors

By default we use 100/300 dimension vectors, to use higher dimension vectors (more than 384, check `highDimDataSets` in `gradle/knn.gradle`), you need to:

1. run `./gradlew vectors-mpnet` or `./gradlew vectors-minilm` depend on your needs (this step will run `infer_token_vectors.py` for you, and then generate task and document vectors)
2. run `src/python/localrun.py` (see instructions inside `src/python/vector-test.py`) or `src/python/knnPerfTest.py` (see instructions inside the file) of your choice, 

To test vector search with [Cohere/wikipedia-22-12-en-embeddings](https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings) dataset, you need to do:
1. run `python src/python/infer_token_vectors_cohere.py -d 10000000 -q 10000` to generate vectors
in the format that luceneutil vector search can understand. Instead of `10000000` increase the number of documents to `100000000` if you want to run vector search on 10M documents.
2. In `src/python/knnPerfTest.py` uncomment lines that define doc and query vectors for cohere dataset.
3. run `src/python/knnPerfTest.py` 

# Running the facets benchmark

## Compare facet implementations

There are currently two facets implementations - one that first collects document IDs and then computes facets
in a separate phase, and a new implementation that computes facets during collection.

To compare performance for the two implementations run

```
python src/python/localrunFacets.py -source facetsWikimediumAll
```

Note that only comparison of taxonomy based facets is supported at the moment. We need to add SSDV facets support
to the sandbox facets module, as well as add support for other facet types to this package.
