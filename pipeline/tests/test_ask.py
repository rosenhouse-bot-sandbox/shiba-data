import json, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask

MODEL = "claude-haiku-5-5"


class Fake:
    def __init__(self, reply):
        self.reply, self.asked = reply, []

    def __call__(self, model, text):
        self.asked.append((model, text))
        return self.reply


class AnswerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.saved = self.root / "answers"
        self.task = self.root / "tasks" / "P-1.md"
        self.task.parent.mkdir()
        self.task.write_text("Read this.")

    def answer(self, model=MODEL, reply='[{"key": "a"}]'):
        fake = Fake(reply)
        return ask.answer([self.task], model, self.saved, fake), fake

    def test_asks_once_and_then_reuses_the_saved_answer(self):
        missing, fake = self.answer()
        self.assertEqual((missing, len(fake.asked)), ([], 1))
        missing, fake = self.answer()
        self.assertEqual((missing, fake.asked), ([], []))
        self.assertEqual(json.loads(self.task.with_suffix(".json").read_text()), [{"key": "a"}])
        saved = json.loads(next(self.saved.iterdir()).read_text())
        self.assertEqual(saved, {"model": MODEL, "task": "P-1.md", "reply": '[{"key": "a"}]'})

    def test_asks_again_when_the_model_or_task_changes(self):
        self.answer()
        self.assertEqual(len(self.answer("claude-sonnet-5-5")[1].asked), 1)
        self.task.write_text("Read this too.")
        self.assertEqual(len(self.answer()[1].asked), 1)
        self.assertEqual(len(list(self.saved.iterdir())), 3)

    def test_without_an_asker_lists_tasks_with_no_saved_answer(self):
        self.assertEqual(ask.answer([self.task], MODEL, self.saved, None), [self.task])
        self.assertFalse(self.task.with_suffix(".json").exists())

    def test_reads_a_fenced_array_and_drops_a_reply_that_is_not_an_array(self):
        self.assertEqual(self.answer(reply='Here:\n```json\n[{"id": 0}]\n```')[0], [])
        self.assertEqual(json.loads(self.task.with_suffix(".json").read_text()), [{"id": 0}])
        self.task.write_text("Another task.")
        for reply in ("Sorry, no.", '{"id": 0}', '[{"id": 0}, 1]'):
            missing, _ = self.answer(reply=reply)
            self.assertEqual(missing, [self.task])
        self.assertEqual(len(list(self.saved.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
