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
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Controls a perf stat session through its control and acknowledgement FIFOs. */
final class PerfControl implements AutoCloseable {
  private static final long DEFAULT_ACK_TIMEOUT_MSEC = 10000;
  private static final long ACK_READER_CLEANUP_TIMEOUT_MSEC = 1000;

  private final BufferedWriter control;
  private final BufferedReader acknowledgement;
  private final long acknowledgementTimeoutMsec;

  PerfControl(Path controlPath, Path acknowledgementPath) throws IOException {
    BufferedWriter openedControl = Files.newBufferedWriter(controlPath, StandardCharsets.UTF_8);
    BufferedReader openedAcknowledgement;
    try {
      openedAcknowledgement = Files.newBufferedReader(acknowledgementPath, StandardCharsets.UTF_8);
    } catch (IOException ioe) {
      try {
        openedControl.close();
      } catch (IOException closeException) {
        ioe.addSuppressed(closeException);
      }
      throw ioe;
    }
    this.control = openedControl;
    this.acknowledgement = openedAcknowledgement;
    this.acknowledgementTimeoutMsec = DEFAULT_ACK_TIMEOUT_MSEC;
  }

  PerfControl(Writer control, Reader acknowledgement) {
    this(control, acknowledgement, DEFAULT_ACK_TIMEOUT_MSEC);
  }

  PerfControl(Writer control, Reader acknowledgement, long acknowledgementTimeoutMsec) {
    if (acknowledgementTimeoutMsec < 1) {
      throw new IllegalArgumentException("acknowledgement timeout must be at least 1 msec");
    }
    this.control = control instanceof BufferedWriter ? (BufferedWriter) control : new BufferedWriter(control);
    this.acknowledgement = acknowledgement instanceof BufferedReader ? (BufferedReader) acknowledgement : new BufferedReader(acknowledgement);
    this.acknowledgementTimeoutMsec = acknowledgementTimeoutMsec;
  }

  void enableAndWaitForAck() throws IOException {
    commandAndWaitForAck("enable");
  }

  void disableAndWaitForAck() throws IOException {
    commandAndWaitForAck("disable");
  }

  private void commandAndWaitForAck(String command) throws IOException {
    control.write(command);
    control.write('\n');
    control.flush();
    String response = readAcknowledgement(command);
    if ("ack".equals(response) == false) {
      throw new IOException("perf did not acknowledge " + command + " command; received " + (response == null ? "end of stream" : "\"" + response + "\""));
    }
  }

  private String readAcknowledgement(String command) throws IOException {
    FutureTask<String> read = new FutureTask<>(acknowledgement::readLine);
    Thread readerThread = new Thread(read, "perf-ack-reader");
    readerThread.setDaemon(true);
    readerThread.start();
    try {
      return read.get(acknowledgementTimeoutMsec, TimeUnit.MILLISECONDS);
    } catch (TimeoutException timeout) {
      IOException failure = new IOException("timed out waiting for perf acknowledgement of " + command + " command", timeout);
      abortAcknowledgementRead(read, readerThread, failure);
      throw failure;
    } catch (InterruptedException interrupted) {
      IOException failure = new IOException("interrupted while waiting for perf acknowledgement of " + command + " command", interrupted);
      abortAcknowledgementRead(read, readerThread, failure);
      Thread.currentThread().interrupt();
      throw failure;
    } catch (ExecutionException execution) {
      Throwable cause = execution.getCause();
      if (cause instanceof IOException) {
        throw (IOException) cause;
      }
      throw new IOException("failed while waiting for perf acknowledgement of " + command + " command", cause);
    }
  }

  private void abortAcknowledgementRead(FutureTask<String> read, Thread readerThread, IOException failure) {
    read.cancel(true);
    try {
      acknowledgement.close();
    } catch (IOException closeException) {
      failure.addSuppressed(closeException);
    }
    try {
      readerThread.join(ACK_READER_CLEANUP_TIMEOUT_MSEC);
      if (readerThread.isAlive()) {
        failure.addSuppressed(new IOException("perf acknowledgement reader did not stop after its input was closed"));
      }
    } catch (InterruptedException interrupted) {
      Thread.currentThread().interrupt();
      failure.addSuppressed(interrupted);
    }
  }

  @Override
  public void close() throws IOException {
    IOException failure = null;
    try {
      control.close();
    } catch (IOException ioe) {
      failure = ioe;
    }
    try {
      acknowledgement.close();
    } catch (IOException ioe) {
      if (failure == null) {
        failure = ioe;
      } else {
        failure.addSuppressed(ioe);
      }
    }
    if (failure != null) {
      throw failure;
    }
  }
}
