"""Answers model task files: <dir>/<name>.md gets its answer, a JSON array, in <dir>/<name>.json.

Each answer is saved in data/<year>/answers, keyed by a hash of the model, the effort if any, and the task's text.
A rerun reuses saved answers, so only new or changed tasks call a model.
"""
import datetime, hashlib, json, os, re, threading, time, urllib.request

MAX_TOKENS = 64000
# A model sometimes replies in prose, so a bad reply is asked again.
ATTEMPTS = 3
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
POLL_SECONDS = 30
REUSE = datetime.timedelta(days=7)


def key(model, text, effort=None):
    # Without an effort, the key has its original format.
    named = f"{model}\n{text}" if effort is None else json.dumps([model, effort, text])
    return hashlib.sha256(named.encode()).hexdigest()[:16]


def array(reply):
    """The reply's JSON array of objects, or None. Takes the last fenced block if there is one."""
    fenced = re.findall(r"```(?:json)?\n(.*?)```", reply, re.S)
    try:
        found = json.loads(fenced[-1] if fenced else reply)
    except json.JSONDecodeError:
        return None
    return found if isinstance(found, list) and all(isinstance(x, dict) for x in found) else None


def write(path, value):
    """Writes JSON whole or not at all, so a killed run leaves no truncated file."""
    with open(path + ".tmp", "w") as f:
        json.dump(value, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(path + ".tmp", path)


def answer(tasks, model, saved, asker, effort=None):
    """Writes each task's answer. Returns the tasks left without one: no saved answer and no asker, or a bad reply.
    asker(model, effort, {key: text}) returns {key: (reply, usage)} and gets every unasked task at once.
    A new answer saves the token usage of all its attempts."""
    os.makedirs(saved, exist_ok=True)
    keys, texts, names = {}, {}, {}
    for task in tasks:
        with open(task) as f:
            text = f.read()
        keys[task] = k = key(model, text, effort)
        if not os.path.exists(os.path.join(saved, k + ".json")):
            texts[k] = text
            names.setdefault(k, os.path.basename(task))
    if asker and texts:
        usage = {k: {} for k in texts}
        for _ in range(ATTEMPTS):
            for k, (reply, used) in asker(model, effort, texts).items():
                usage[k] = {f: usage[k].get(f, 0) + n for f, n in used.items()}
                if array(reply) is None:
                    print(f"{names[k]}: {model} did not reply with a JSON array")
                    continue
                write(os.path.join(saved, k + ".json"), {"model": model}
                      | ({"effort": effort} if effort is not None else {})
                      | ({"batch": True} if getattr(asker, "batch", False) else {})
                      | {"task": names[k], "reply": reply, "usage": usage[k]})
                del texts[k]
            if not texts:
                break
    missing = []
    for task in tasks:
        path = os.path.join(saved, keys[task] + ".json")
        if os.path.exists(path):
            with open(path) as f:
                write(os.path.splitext(task)[0] + ".json", array(json.load(f)["reply"]))
        else:
            missing.append(task)
    return missing


def github_identity_token():
    """A fresh GitHub Actions OIDC token. Each is single-use and expires in about five minutes."""
    request = urllib.request.Request(os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=https://api.anthropic.com",
                                     headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urllib.request.urlopen(request) as r:
        return json.load(r)["value"]


def api():
    """An asker that sends Message Batches to the Claude API. In GitHub Actions it signs in through workload identity federation."""
    import anthropic

    if "ACTIONS_ID_TOKEN_REQUEST_URL" in os.environ:
        from anthropic.lib.credentials import WorkloadIdentityCredentials
        client = anthropic.Anthropic(max_retries=5, credentials=WorkloadIdentityCredentials(
            identity_token_provider=github_identity_token,
            federation_rule_id=os.environ["ANTHROPIC_FEDERATION_RULE_ID"],
            organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
            service_account_id=os.environ["ANTHROPIC_SERVICE_ACCOUNT_ID"],
            workspace_id=os.environ["ANTHROPIC_WORKSPACE_ID"]))
    else:
        client = anthropic.Anthropic(max_retries=5)
    return Batches(client)


def reply(message):
    """The message's text and its token usage."""
    usage = {k: getattr(message.usage, k) or 0 for k in USAGE_FIELDS}
    if message.stop_reason != "end_turn":
        return f"(stopped: {message.stop_reason})", usage
    return "".join(b.text for b in message.content if b.type == "text"), usage


class Batches:
    """An asker that sends each round of tasks as one Message Batch, at half the price of single requests.
    A rerun after a timeout reuses each succeeded result of this week's batches once, instead of paying again."""
    batch = True

    def __init__(self, client):
        self.batches, self.lock, self.earlier = client.messages.batches, threading.Lock(), None

    def ended(self, batch):
        while batch.processing_status != "ended":
            time.sleep(POLL_SECONDS)
            batch = self.batches.retrieve(batch.id)
        return batch

    def results(self, batch_id):
        found = {}
        for r in self.batches.results(batch_id):
            if r.result.type == "succeeded":
                found[r.custom_id] = r.result
            else:
                print(f"{r.custom_id}: {r.result.type} {getattr(r.result, 'error', '')}")
        return found

    def reuse(self, keys):
        with self.lock:
            if self.earlier is None:
                self.earlier, since = {}, datetime.datetime.now(datetime.timezone.utc) - REUSE
                for b in self.batches.list(limit=100):
                    if b.created_at < since:
                        break
                    # The list starts with the newest batch, whose results win.
                    self.earlier = self.results(self.ended(b).id) | self.earlier
            return {k: self.earlier.pop(k) for k in keys if k in self.earlier}

    def __call__(self, model, effort, texts):
        found = self.reuse(texts)
        asked = [{"custom_id": k, "params": {"model": model, "max_tokens": MAX_TOKENS,
                                             "messages": [{"role": "user", "content": t}]}
                  | ({"output_config": {"effort": effort}} if effort is not None else {})}
                 for k, t in texts.items() if k not in found]
        if asked:
            found |= self.results(self.ended(self.batches.create(requests=asked)).id)
        return {k: reply(r.message) for k, r in found.items()}
