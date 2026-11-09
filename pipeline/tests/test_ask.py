import contextlib, datetime, io, json, os, pathlib, sys, tempfile, types, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask

MODEL = "claude-haiku-5-5"
USAGE = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


@contextlib.contextmanager
def printing(test, expected):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        yield
    test.assertIn(expected, out.getvalue())


def each(ask_one):
    """An asker that answers each task with ask_one(model, text, effort)."""
    def asker(model, effort, texts):
        return {k: ask_one(model, t, effort) for k, t in texts.items()}
    return asker


class Fake:
    def __init__(self, *replies):
        self.replies, self.asked, self.rounds = replies, [], []

    def __call__(self, model, effort, texts):
        self.rounds.append(sorted(texts.values()))
        return {k: self.one(model, t, effort) for k, t in texts.items()}

    def one(self, model, text, effort):
        self.asked.append((model, text, effort))
        return self.replies[min(len(self.asked), len(self.replies)) - 1], USAGE


class AnswerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.saved = self.root / "answers"
        self.task = self.root / "tasks" / "P-1.md"
        self.task.parent.mkdir()
        self.task.write_text("Read this.")

    def answer(self, model=MODEL, reply='[{"key": "a"}]', effort=None):
        fake = Fake(reply)
        return ask.answer([self.task], model, self.saved, fake, effort), fake

    def saved_answers(self):
        return [json.loads(p.read_text()) for p in self.saved.iterdir()]

    def test_asks_once_and_then_reuses_the_saved_answer(self):
        missing, fake = self.answer()
        self.assertEqual((missing, len(fake.asked)), ([], 1))
        missing, fake = self.answer()
        self.assertEqual((missing, fake.asked), ([], []))
        self.assertEqual(json.loads(self.task.with_suffix(".json").read_text()), [{"key": "a"}])
        self.assertEqual(self.saved_answers(), [{"model": MODEL, "task": "P-1.md", "reply": '[{"key": "a"}]', "usage": USAGE}])

    def test_asks_for_every_unanswered_task_at_once_and_once_per_text(self):
        twin, other = self.root / "tasks" / "P-2.md", self.root / "tasks" / "P-3.md"
        twin.write_text("Read this.")
        other.write_text("Read that.")
        fake = Fake("[]")
        self.assertEqual(ask.answer([self.task, twin, other], MODEL, self.saved, fake), [])
        self.assertEqual(fake.rounds, [["Read that.", "Read this."]])
        self.assertEqual(json.loads(twin.with_suffix(".json").read_text()), [])
        self.assertEqual(sorted(a["task"] for a in self.saved_answers()), ["P-1.md", "P-3.md"])

    def test_asks_again_only_for_the_replies_that_were_not_arrays(self):
        good = self.root / "tasks" / "P-2.md"
        good.write_text("Read that.")
        fake = each(lambda model, text, effort: ("[]" if text == "Read that." else "Sorry, no.", USAGE))
        rounds = []
        asker = lambda model, effort, texts: rounds.append(sorted(texts.values())) or fake(model, effort, texts)
        with printing(self, "P-1.md: claude-haiku-5-5 did not reply with a JSON array"):
            self.assertEqual(ask.answer([self.task, good], MODEL, self.saved, asker), [self.task])
        self.assertEqual(rounds, [["Read that.", "Read this."]] + [["Read this."]] * (ask.ATTEMPTS - 1))

    def test_saves_that_a_batch_answered(self):
        fake = Fake("[]")
        fake.batch = True
        ask.answer([self.task], MODEL, self.saved, fake)
        self.assertTrue(self.saved_answers()[0]["batch"])

    def test_without_an_effort_the_key_is_unchanged(self):
        self.assertEqual(ask.key(MODEL, "Read this."), "b841d88300394ed2")

    def test_sends_the_effort_and_saves_each_effort_under_its_own_key(self):
        self.answer()
        self.assertEqual(self.answer(effort="low")[1].asked, [(MODEL, "Read this.", "low")])
        self.assertEqual(self.answer(effort="high")[1].asked, [(MODEL, "Read this.", "high")])
        self.assertEqual(sorted(a.get("effort", "") for a in self.saved_answers()), ["", "high", "low"])

    def test_reuses_the_answer_saved_at_the_same_effort(self):
        self.answer(effort="low")
        self.assertEqual(self.answer(effort="low")[1].asked, [])

    def test_asks_again_when_the_model_or_task_changes(self):
        self.answer()
        self.assertEqual(len(self.answer("claude-sonnet-5-5")[1].asked), 1)
        self.task.write_text("Read this too.")
        self.assertEqual(len(self.answer()[1].asked), 1)
        self.assertEqual(len(list(self.saved.iterdir())), 3)

    def test_without_an_asker_lists_tasks_with_no_saved_answer(self):
        self.assertEqual(ask.answer([self.task], MODEL, self.saved, None), [self.task])
        self.assertFalse(self.task.with_suffix(".json").exists())

    def test_asks_again_after_a_reply_that_is_not_an_array(self):
        fake = Fake("Sorry, no.", '[{"id": 0}]')
        with printing(self, "did not reply with a JSON array"):
            self.assertEqual(ask.answer([self.task], MODEL, self.saved, fake), [])
        self.assertEqual(len(fake.asked), 2)
        both = {k: 2 * v for k, v in USAGE.items()}
        self.assertEqual(self.saved_answers()[0]["usage"], both)
        fake = Fake("Sorry, no.")
        self.task.write_text("Another task.")
        with printing(self, "did not reply with a JSON array"):
            self.assertEqual(ask.answer([self.task], MODEL, self.saved, fake), [self.task])
        self.assertEqual(len(fake.asked), ask.ATTEMPTS)

    def test_reads_a_fenced_array_and_drops_a_reply_that_is_not_an_array(self):
        self.assertEqual(self.answer(reply='Here:\n```json\n[{"id": 0}]\n```')[0], [])
        self.assertEqual(json.loads(self.task.with_suffix(".json").read_text()), [{"id": 0}])
        self.task.write_text("Another task.")
        for reply in ("Sorry, no.", '{"id": 0}', '[{"id": 0}, 1]'):
            with printing(self, "did not reply with a JSON array"):
                missing, _ = self.answer(reply=reply)
            self.assertEqual(missing, [self.task])
        self.assertEqual(len(list(self.saved.iterdir())), 1)


class Message:
    def __init__(self, stop_reason, text):
        self.stop_reason = stop_reason
        self.content = [types.SimpleNamespace(type="thinking"), types.SimpleNamespace(type="text", text=text)]
        self.usage = types.SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=None,
                                           cache_creation_input_tokens=5)


def result(custom_id, kind="succeeded", message=None):
    return types.SimpleNamespace(custom_id=custom_id, result=types.SimpleNamespace(type=kind, message=message))


class Client:
    """Fake Message Batches. Each batch ends after one poll, with message_for(params) for each request."""

    def __init__(self, message_for, earlier=(), kind="succeeded", age=datetime.timedelta(days=1), unfinished=False):
        """earlier lists the results of earlier batches, newest first."""
        self.message_for, self.kind, self.created, self.polls = message_for, kind, [], 0
        self.batches = {f"old{i}": ("in_progress" if unfinished else "ended", rs) for i, rs in enumerate(earlier)}
        self.created_at = datetime.datetime.now(datetime.timezone.utc) - age
        self.messages = types.SimpleNamespace(batches=self)

    def create(self, requests):
        self.created.append(requests)
        batch_id = f"new{len(self.created)}"
        self.batches[batch_id] = ("in_progress", [result(r["custom_id"], self.kind, self.message_for(r["params"]))
                                                   for r in requests])
        return types.SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id):
        self.polls += 1
        self.batches[batch_id] = ("ended", self.batches[batch_id][1])
        return types.SimpleNamespace(id=batch_id, processing_status="ended")

    def results(self, batch_id):
        status, rs = self.batches[batch_id]
        assert status == "ended"
        return iter(rs)

    def list(self, limit):
        return [types.SimpleNamespace(id=i, processing_status=s, created_at=self.created_at)
                for i, (s, _) in self.batches.items()]


class BatchesTest(unittest.TestCase):
    def asker(self, client):
        with mock.patch.dict(sys.modules, anthropic=types.SimpleNamespace(Anthropic=lambda **_: client)), \
                mock.patch.dict(os.environ), mock.patch.object(ask.time, "sleep"):
            os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
            return ask.api()

    def ask(self, asker, *args):
        with mock.patch.object(ask.time, "sleep"):
            return asker(*args)

    def test_sends_one_batch_with_the_effort_only_when_given_and_returns_text_and_usage(self):
        client = Client(lambda params: Message("end_turn", "[]"))
        asker = self.asker(client)
        self.assertTrue(asker.batch)
        usage = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5}
        self.assertEqual(self.ask(asker, MODEL, None, {"a": "Read this.", "b": "Read that."}),
                         {"a": ("[]", usage), "b": ("[]", usage)})
        self.ask(asker, MODEL, "low", {"c": "Read this."})
        first, second = client.created
        self.assertEqual(first, [{"custom_id": "a", "params": {"model": MODEL, "max_tokens": ask.MAX_TOKENS,
                                  "messages": [{"role": "user", "content": "Read this."}]}},
                                 {"custom_id": "b", "params": {"model": MODEL, "max_tokens": ask.MAX_TOKENS,
                                  "messages": [{"role": "user", "content": "Read that."}]}}])
        self.assertEqual(second[0]["params"]["output_config"], {"effort": "low"})
        self.assertEqual(client.polls, 2)

    def test_a_reply_that_did_not_end_its_turn_says_why_and_keeps_its_usage(self):
        asker = self.asker(Client(lambda params: Message("max_tokens", "[{")))
        reply, usage = self.ask(asker, MODEL, None, {"a": "Read this."})["a"]
        self.assertEqual((reply, usage["output_tokens"]), ("(stopped: max_tokens)", 20))

    def test_leaves_out_requests_that_did_not_succeed(self):
        asker = self.asker(Client(lambda params: None, kind="errored"))
        with printing(self, "a: errored"):
            self.assertEqual(self.ask(asker, MODEL, None, {"a": "Read this."}), {})

    def test_reuses_each_earlier_succeeded_result_once_instead_of_asking_again(self):
        old = [result("a", message=Message("end_turn", "[1]")), result("b", "errored")]
        client = Client(lambda params: Message("end_turn", "[2]"), earlier=[old])
        asker = self.asker(client)
        with printing(self, "b: errored"):
            got = self.ask(asker, MODEL, None, {"a": "Read this.", "b": "Read that."})
        self.assertEqual({k: r for k, (r, _) in got.items()}, {"a": "[1]", "b": "[2]"})
        self.assertEqual([[r["custom_id"] for r in rs] for rs in client.created], [["b"]])
        got = self.ask(asker, MODEL, None, {"a": "Read this."})
        self.assertEqual(got["a"][0], "[2]")

    def test_does_not_reuse_results_of_batches_older_than_a_week(self):
        old = [result("a", message=Message("end_turn", "[1]"))]
        client = Client(lambda params: Message("end_turn", "[2]"), earlier=[old], age=datetime.timedelta(days=8))
        self.assertEqual(self.ask(self.asker(client), MODEL, None, {"a": "Read this."})["a"][0], "[2]")

    def test_waits_for_an_unfinished_earlier_batch_and_reuses_its_results(self):
        old = [result("a", message=Message("end_turn", "[1]"))]
        client = Client(lambda params: Message("end_turn", "[2]"), earlier=[old], unfinished=True)
        self.assertEqual(self.ask(self.asker(client), MODEL, None, {"a": "Read this."})["a"][0], "[1]")
        self.assertEqual((client.created, client.polls), ([], 1))

    def test_reuses_the_newest_earlier_result(self):
        newer, older = [result("a", message=Message("end_turn", "[new]"))], [result("a", message=Message("end_turn", "[old]"))]
        client = Client(lambda params: None, earlier=[newer, older])
        self.assertEqual(self.ask(self.asker(client), MODEL, None, {"a": "Read this."})["a"][0], "[new]")

    def test_says_why_a_request_did_not_succeed(self):
        client = Client(lambda params: None, kind="errored")
        with mock.patch("builtins.print") as printed:
            self.ask(self.asker(client), MODEL, None, {"a": "Read this."})
        self.assertIn("a: errored", printed.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
