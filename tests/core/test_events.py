import json
import tempfile
import unittest
from pathlib import Path

from app.core.events import EventBus, follow, sse_stream


class TestEventBus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_emit_appends_json_lines_with_timestamp(self):
        bus = EventBus("demo", self.dir)
        bus({"event": "a"})
        bus.emit({"event": "b", "ts": 1})
        lines = [json.loads(l) for l in bus.path.read_text().splitlines()]
        self.assertEqual([l["event"] for l in lines], ["a", "b"])
        self.assertIn("ts", lines[0])
        self.assertEqual(lines[1]["ts"], 1)

    def test_emit_never_raises(self):
        bus = EventBus("demo", self.dir / "file-not-dir")
        (self.dir / "file-not-dir").write_text("x")
        bus({"event": "lost"})  # must not raise

    def test_rotation(self):
        bus = EventBus("demo", self.dir, max_bytes=50)
        for i in range(10):
            bus({"event": "x", "i": i})
        self.assertTrue(bus.path.with_suffix(".jsonl.1").exists())
        self.assertLess(bus.path.stat().st_size, 200)

    def _driver(self, bus, writes):
        """sleep() replacement that performs one scripted write per call."""
        writes = list(writes)

        def sleep(_s):
            if writes:
                writes.pop(0)()
        return sleep

    def test_follow_starts_at_end_and_sees_new_lines(self):
        bus = EventBus("demo", self.dir)
        bus({"event": "old"})
        gen = follow(bus.path, sleep=self._driver(bus, [lambda: bus({"event": "new"})]))
        self.assertEqual(json.loads(next(gen))["event"], "new")

    def test_follow_waits_for_file_creation(self):
        bus = EventBus("later", self.dir)
        gen = follow(bus.path, sleep=self._driver(bus, [lambda: None, lambda: bus({"event": "first"})]))
        self.assertEqual(json.loads(next(gen))["event"], "first")

    def test_follow_survives_rotation(self):
        bus = EventBus("demo", self.dir, max_bytes=10)
        bus({"event": "seed"})
        gen = follow(bus.path, sleep=self._driver(bus, [
            lambda: bus({"event": "before"}),
            lambda: bus({"event": "after_rotation"}),
        ]))
        got = [json.loads(next(gen))["event"] for _ in range(2)]
        self.assertEqual(got, ["before", "after_rotation"])

    def test_keepalive(self):
        t = [0.0]

        def clock():
            return t[0]

        def sleep(s):
            t[0] += s
        gen = follow(self.dir / "none.jsonl", keepalive=1.0, clock=clock, sleep=sleep)
        self.assertIsNone(next(gen))

    def test_sse_stream_formats_and_skips_garbage(self):
        path = self.dir / "demo.jsonl"
        path.write_text("")
        writes = [lambda: path.open("a").write("not json\n"),
                  lambda: path.open("a").write('{"event":"ok"}\n')]

        def sleep(_s):
            if writes:
                writes.pop(0)()
        gen = sse_stream(path, sleep=sleep)
        self.assertEqual(next(gen), 'data: {"event":"connected"}\n\n')
        self.assertEqual(next(gen), 'data: {"event":"ok"}\n\n')
