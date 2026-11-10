"""Records which CMS fields a computation reads, so a trace can list the Landscape fields behind each plans.csv field."""


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


def logged(compute, *args):
    """compute's result and the unique (file, field, value) reads it made, in order."""
    log = []
    result = compute(*(Row(a, file, log) for file, a in args))
    return result, list(dict.fromkeys(log))
