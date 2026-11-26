"""Links to the code that gives each column its rule, at a build's commit."""
import ast
import functools
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))
import present  # noqa: E402

REPO_URL = "https://github.com/rosenhouse-bot-sandbox/shiba-data"
TABLES = {"main": "COLUMNS", "dvha": "DVHA"}


@functools.cache
def present_code():
    """present.py's module-level assignments and functions, by name."""
    with open(present.__file__) as f:
        tree = ast.parse(f.read())
    assigned = {n.targets[0].id: n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    return assigned, {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def entry(table, key):
    """The key and value nodes of a dict literal's entry."""
    (found,) = [(k, v) for k, v in zip(table.keys, table.values) if k is not None and ast.literal_eval(k) == key]
    return found


def rule_entry(sheet, col, version):
    """(name, first node, value node) of the code that gives a column its rule at a version, as present.rule picks it."""
    assigned, _ = present_code()
    for i, (since, _) in enumerate(present.EARLIER_RULES.get((sheet, col), ())):
        if version < since:
            break
    else:
        table = TABLES[sheet]
        return (f"{col} in {table}", *entry(assigned[table].value, col))
    if sheet == "main":
        # Main's earlier rules come from a comprehension over one dict literal, then from CHART_18.
        if i == 0:
            return (f"{col} in EARLIER_RULES", *entry(assigned["EARLIER_RULES"].value.right.generators[0].iter.func.value, col))
        return (f"{col} in CHART_18", *entry(assigned["CHART_18"].value, col))
    pair = entry(assigned["EARLIER_RULES"].value.left, (sheet, col))[1].elts[i]
    return f"{col} in EARLIER_RULES", pair, pair.elts[1]


def links(sheet, col, version, sha):
    """The entry that gives a column its rule at a version, then each function and module-level name the rule uses,
    in the order they first appear."""
    assigned, functions = present_code()
    link = lambda name, node, end: dict(name=name, url=f"{REPO_URL}/blob/{sha}/pipeline/present.py#L{node.lineno}-L{end.end_lineno}")
    name, first, value = rule_entry(sheet, col, version)
    out, seen = [link(name, first, value)], set()

    def follow(node):
        for n in sorted((n for n in ast.walk(node) if isinstance(n, ast.Name)), key=lambda n: (n.lineno, n.col_offset)):
            if n.id in seen or (n.id not in functions and n.id not in assigned):
                continue
            seen.add(n.id)
            if n.id in functions:
                out.append(link(n.id, functions[n.id], functions[n.id]))
            else:
                out.append(link(n.id, assigned[n.id], assigned[n.id]))
                follow(assigned[n.id].value)
    follow(value)
    return out


def resolve(data_dir, sha):
    """{sheet: {column: links}} at the pinned version."""
    version = present.current(data_dir, "")
    return {sheet: {col: links(sheet, col, version, sha) for col in rules} for sheet, (rules, _) in present.SHEETS.items()}
