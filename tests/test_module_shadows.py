"""A local must not shadow a module the same scope calls into.

`_show_dict_popup_at` binds `content` to the popover's box. Its nested worker
then called `content.language_code(...)`, which resolved to that `Gtk.Box`, so
every double-click on a word raised `AttributeError` in the task thread — and
the task machinery reports a failed lookup as "no entry", so the dictionary
peek looked empty rather than broken. It shipped that way in 1.6.2, past 2,062
tests, because nothing exercised the caller: the language rule itself had its
own tests one layer down.

It is the second time the trap has bitten. Naming a parameter `_` shadows
gettext for a whole function the same way (`i18n.py`, and GUIDANCE §4.16).

This is the narrow, quiet version of the check. A local sharing a module's
name is fine and common — `content` for a box, `motion` for a gesture
controller — and is only a defect when the scope ALSO reaches for something
that only the module has. So it flags one shape and no other: an attribute
access on the shadowed name whose attribute is a top-level name in that
module.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module_names(path):
    """Every top-level name a repo module defines."""
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets
                         if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            names.add(node.target.id)
    return names


def _imported_here(tree):
    """`import x` at the top of a file, where x.py is one of ours."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            name = (alias.asname or alias.name).split('.')[0]
            source = ROOT / f'{alias.name}.py'
            if alias.asname is None and source.exists():
                out[name] = source
    return out


def _shadows(path):
    tree = ast.parse(path.read_text())
    modules = _imported_here(tree)
    if not modules:
        return []
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # The binding shadows the module for this whole scope, closures
        # included — which is exactly how the worker inside the peek came to
        # be holding a Gtk.Box.
        bound = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) \
                    and node.id in modules:
                bound.setdefault(node.id, node.lineno)
            elif isinstance(node, ast.arg) and node.arg in modules:
                bound.setdefault(node.arg, node.lineno)
        for name, line in bound.items():
            defined = _module_names(modules[name])
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) \
                        and isinstance(node.value, ast.Name) \
                        and node.value.id == name \
                        and node.attr in defined \
                        and node.lineno != line:
                    found.append(
                        f'{path.name}:{node.lineno}: {name}.{node.attr}() '
                        f'reaches for the module, but `{name}` is a local '
                        f'from line {line} (in {fn.name}, line {fn.lineno})')
    return sorted(set(found))


def test_no_local_shadows_a_module_its_scope_calls():
    hits = []
    for path in sorted(ROOT.glob('*.py')):
        hits.extend(_shadows(path))
    assert not hits, '\n'.join(hits)


def test_the_check_can_see_the_bug_it_was_written_for(tmp_path):
    """The guard's own guard: a test that cannot fail protects nothing."""
    target = ROOT / '_shadow_probe_target.py'
    probe = ROOT / '_shadow_probe.py'
    try:
        target.write_text('def language_code(x):\n    return x\n')
        probe.write_text(
            'import _shadow_probe_target\n\n\n'
            'def build():\n'
            '    _shadow_probe_target = object()\n'
            '    return _shadow_probe_target.language_code(1)\n')
        hits = _shadows(probe)
    finally:
        # Both, always: a probe left in the repo root would fail the check
        # above on the next run and look like a real finding.
        probe.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
    assert len(hits) == 1 and 'language_code' in hits[0]
