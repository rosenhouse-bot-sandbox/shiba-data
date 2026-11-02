import json, os, pathlib, sys, tempfile, types, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask

MODEL = "claude-haiku-5-5"
USAGE = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class Fake:
    def __init__(self, *replies):
        self.replies, self.asked = replies, []

    def __call__(self, model, text, effort):
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

    def test_without_an_effort_the_key_is_unchanged(self):
        self.assertEqual(ask.key(MODEL, "Read this."), "b841d88300394ed2")

    def test_sends_the_effort_and_saves_it_under_its_own_key(self):
        self.answer()
        missing, fake = self.answer(effort="low")
        self.assertEqual((missing, fake.asked), ([], [(MODEL, "Read this.", "low")]))
        self.assertEqual(len(self.answer(effort="high")[1].asked), 1)
        self.assertEqual(self.answer(effort="low")[1].asked, [])
        self.assertEqual(sorted(a.get("effort", "") for a in self.saved_answers()), ["", "high", "low"])

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
        self.assertEqual(ask.answer([self.task], MODEL, self.saved, fake), [])
        self.assertEqual(len(fake.asked), 2)
        both = {k: 2 * v for k, v in USAGE.items()}
        self.assertEqual(self.saved_answers()[0]["usage"], both)
        fake = Fake("Sorry, no.")
        self.task.write_text("Another task.")
        self.assertEqual(ask.answer([self.task], MODEL, self.saved, fake), [self.task])
        self.assertEqual(len(fake.asked), ask.ATTEMPTS)

    def test_reads_a_fenced_array_and_drops_a_reply_that_is_not_an_array(self):
        self.assertEqual(self.answer(reply='Here:\n```json\n[{"id": 0}]\n```')[0], [])
        self.assertEqual(json.loads(self.task.with_suffix(".json").read_text()), [{"id": 0}])
        self.task.write_text("Another task.")
        for reply in ("Sorry, no.", '{"id": 0}', '[{"id": 0}, 1]'):
            missing, _ = self.answer(reply=reply)
            self.assertEqual(missing, [self.task])
        self.assertEqual(len(list(self.saved.iterdir())), 1)


class Message:
    def __init__(self, stop_reason, text):
        self.stop_reason = stop_reason
        self.content = [types.SimpleNamespace(type="thinking"), types.SimpleNamespace(type="text", text=text)]
        self.usage = types.SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=None,
                                           cache_creation_input_tokens=5, server_tool_use=None)


class ApiTest(unittest.TestCase):
    def asker(self, message):
        sent = []

        class Stream:
            def __init__(self, **kwargs):
                sent.append(kwargs)

            def __enter__(self):
                return types.SimpleNamespace(get_final_message=lambda: message)

            def __exit__(self, *_):
                pass

        client = types.SimpleNamespace(messages=types.SimpleNamespace(stream=Stream))
        sdk = types.SimpleNamespace(Anthropic=lambda **_: client)
        environ = {k: v for k, v in os.environ.items() if k != "ACTIONS_ID_TOKEN_REQUEST_URL"}
        with mock.patch.dict(sys.modules, anthropic=sdk), mock.patch.dict(os.environ, environ, clear=True):
            return ask.api(), sent

    def test_sends_the_effort_only_when_given_and_returns_the_text_and_usage(self):
        asker, sent = self.asker(Message("end_turn", "[]"))
        self.assertEqual(asker(MODEL, "Read this.", None), ("[]", {
            "input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5}))
        asker(MODEL, "Read this.", "low")
        self.assertNotIn("output_config", sent[0])
        self.assertEqual(sent[1]["output_config"], {"effort": "low"})
        self.assertEqual(sent[1]["messages"], [{"role": "user", "content": "Read this."}])

    def test_a_reply_that_did_not_end_its_turn_says_why_and_keeps_its_usage(self):
        asker, _ = self.asker(Message("max_tokens", "[{"))
        reply, usage = asker(MODEL, "Read this.", None)
        self.assertEqual((reply, usage["output_tokens"]), ("(stopped: max_tokens)", 20))


if __name__ == "__main__":
    unittest.main()
