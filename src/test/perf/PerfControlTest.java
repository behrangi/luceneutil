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

import java.io.IOException;
import java.io.PipedReader;
import java.io.PipedWriter;
import java.io.StringReader;
import java.io.StringWriter;

final class PerfControlTest {
  public static void main(String[] args) throws Exception {
    testEnableDisableProtocolAndFlush();
    testUnexpectedAcknowledgementFails();
    testNonNullFrameTerminatorFails();
    testMissingAcknowledgementFails();
    testAcknowledgementTimeout();
  }

  private static void testEnableDisableProtocolAndFlush() throws Exception {
    FlushTrackingWriter commands = new FlushTrackingWriter();
    // perf writes sizeof("ack\n"), including the trailing NUL, for every acknowledgement.
    // The two frames are intentional: a line-only reader leaves the first NUL in front of
    // the disable acknowledgement and makes the second response appear to be "ack" in logs.
    try (PerfControl control = new PerfControl(commands, new StringReader("ack\n\0ack\n\0"))) {
      control.enableAndWaitForAck();
      assertEquals("enable\n", commands.toString(), "enable command");
      assertEquals(1, commands.flushCount, "enable flush count");

      control.disableAndWaitForAck();
      assertEquals("enable\ndisable\n", commands.toString(), "disable command");
      assertEquals(2, commands.flushCount, "disable flush count");
    }
  }

  private static void testUnexpectedAcknowledgementFails() throws Exception {
    assertAckFailure("unexpected\n\0", "received \"unexpected\\u0000\" (line length=10)");
  }

  private static void testNonNullFrameTerminatorFails() throws Exception {
    assertAckFailure("ack\nX", "received \"ackX\" (line length=3)");
  }

  private static void testMissingAcknowledgementFails() throws Exception {
    assertAckFailure("", "received end of stream");
  }

  private static void testAcknowledgementTimeout() throws Exception {
    long startNanos = System.nanoTime();
    try (PipedWriter acknowledgementWriter = new PipedWriter();
         PipedReader acknowledgementReader = new PipedReader(acknowledgementWriter);
         PerfControl control = new PerfControl(new StringWriter(), acknowledgementReader, 100)) {
      control.enableAndWaitForAck();
      throw new AssertionError("expected acknowledgement timeout");
    } catch (IOException expected) {
      assertEquals("timed out waiting for perf acknowledgement of enable command", expected.getMessage(), "timeout failure message");
    }
    long elapsedMsec = (System.nanoTime() - startNanos) / 1000000L;
    if (elapsedMsec >= 2000) {
      throw new AssertionError("acknowledgement timeout took too long: " + elapsedMsec + " msec");
    }
  }

  private static void assertAckFailure(String acknowledgement, String expectedMessage) throws Exception {
    try (PerfControl control = new PerfControl(new StringWriter(), new StringReader(acknowledgement))) {
      control.enableAndWaitForAck();
      throw new AssertionError("expected acknowledgement failure");
    } catch (IOException expected) {
      if (expected.getMessage().contains(expectedMessage) == false) {
        throw new AssertionError("unexpected failure message: " + expected.getMessage());
      }
    }
  }

  private static void assertEquals(Object expected, Object actual, String description) {
    if (expected.equals(actual) == false) {
      throw new AssertionError(description + ": expected " + expected + " but got " + actual);
    }
  }

  private static final class FlushTrackingWriter extends StringWriter {
    int flushCount;

    @Override
    public void flush() {
      flushCount++;
    }
  }
}
