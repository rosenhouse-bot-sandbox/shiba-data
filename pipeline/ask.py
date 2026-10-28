"""Answers model task files: <dir>/<name>.md gets its answer, a JSON array, in <dir>/<name>.json.

Each answer is saved in data/<year>/answers, keyed by a hash of the model and the task's text.
A rerun reuses saved answers, so only new or changed tasks call a model.
"""
import concurrent.futures, hashlib, json, os, re, urllib.request

WORKERS = 8
MAX_TOKENS = 64000


def key(model, text):
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()[:16]


def array(reply):
    """The reply's JSON array, or None. Takes the last fenced block if there is one."""
    fenced = re.findall(r"```(?:json)?\n(.*?)```", reply, re.S)
    try:
        found = json.loads(fenced[-1] if fenced else reply)
    except json.JSONDecodeError:
        return None
    return found if isinstance(found, list) else None


def answer(tasks, model, saved, asker):
    """Writes each task's answer. Returns the tasks left without one: no saved answer and no asker, or a bad reply."""
    os.makedirs(saved, exist_ok=True)

    def one(task):
        with open(task) as f:
            text = f.read()
        path = os.path.join(saved, key(model, text) + ".json")
        if os.path.exists(path):
            with open(path) as f:
                reply = json.load(f)["reply"]
        elif asker:
            reply = asker(model, text)
            if array(reply) is None:
                print(f"{task}: {model} did not reply with a JSON array")
                return task
            with open(path, "w") as f:
                json.dump({"model": model, "task": os.path.basename(task), "reply": reply}, f, indent=1, ensure_ascii=False)
                f.write("\n")
        else:
            return task
        with open(os.path.splitext(task)[0] + ".json", "w") as f:
            json.dump(array(reply), f, indent=1, ensure_ascii=False)
        return None

    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        return [t for t in pool.map(one, tasks) if t]


def github_identity_token():
    """A fresh GitHub Actions OIDC token. Each is single-use and expires in about five minutes."""
    request = urllib.request.Request(os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=https://api.anthropic.com",
                                     headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urllib.request.urlopen(request) as r:
        return json.load(r)["value"]


def api():
    """An asker that calls the Claude API. In GitHub Actions it signs in through workload identity federation."""
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

    def asker(model, text):
        with client.messages.stream(model=model, max_tokens=MAX_TOKENS,
                                    messages=[{"role": "user", "content": text}]) as stream:
            message = stream.get_final_message()
        if message.stop_reason != "end_turn":
            return f"(stopped: {message.stop_reason})"
        return "".join(b.text for b in message.content if b.type == "text")

    return asker
