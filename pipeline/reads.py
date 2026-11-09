"""Records which CMS fields a computation reads, so a trace can list the fields behind each cell."""


# A read of a whole file logs this as its field, and the number of rows as its value.
ROWS = "(rows)"


class Row(dict):
    """A CMS row that logs (file, field, value) for each field read. A field the row lacks reads as ""."""

    def __init__(self, data, file, log):
        super().__init__(data)
        self.file, self.log = file, log

    def get(self, field, default=None):
        self.log.append((self.file, field, dict.get(self, field, "")))
        return dict.get(self, field, default)

    def __getitem__(self, field):
        self.log.append((self.file, field, dict.get(self, field, "")))
        return dict.__getitem__(self, field)


class Plan(dict):
    """A plan's PBP files, {file: [row, ...]}, whose rows log their reads. Reading a file logs its row count."""

    def __init__(self, data, log):
        super().__init__(data)
        self.log = log

    def get(self, file, default=None):
        found = dict.get(self, file)
        self.log.append((file, ROWS, str(len(found or []))))
        return [Row(r, file, self.log) for r in found] if found else default


def logged(compute, *args):
    """compute's result and the unique (file, field, value) reads it made, in order."""
    log = []
    result = compute(*(Plan(a, log) if kind == "plan" else Row(a, kind, log) for kind, a in args))
    return result, list(dict.fromkeys(log))
