"""Every idle and timeout callback in the app says when it stops.

GLib calls an idle or timeout callback again for as long as it returns
something true. The book picker's idle returned what grab_focus() returned,
True, and ran at 99% CPU from the first open in every release up to 1.9.2.
Seven more callbacks had the same shape, `lambda: f() or SOURCE_REMOVE`,
safe only while f returns None.

So a callback may only return what is plainly a yes or a no: None, True,
False, GLib.SOURCE_REMOVE or SOURCE_CONTINUE, a comparison, or a call to
another app function that keeps the same rule. A lambda must end in one of
those constants, as `(f(), GLib.SOURCE_REMOVE)[1]`.
"""
import ast
import glob
import os

ROOT = os.path.join(os.path.dirname(__file__), '..')
ADDERS = {'idle_add', 'timeout_add', 'timeout_add_seconds'}


def _trees():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, '*.py'))):
        with open(path, encoding='utf-8') as fh:
            out[os.path.basename(path)] = ast.parse(fh.read())
    return out


def _defs(trees):
    """{name: [(file, def)]}, leaving out properties: a property is read,
    never handed to GLib."""
    defs = {}
    for fname, tree in trees.items():
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not any(
                    isinstance(d, ast.Name) and d.id == 'property' for d in n.decorator_list):
                defs.setdefault(n.name, []).append((fname, n))
    return defs


def _lookup(name, fname, defs):
    """The defs a name means: the caller's own file's if it has one, as
    `self._layout` there is that file's _layout, else every file's."""
    found = defs.get(name, [])
    own = [d for f, d in found if f == fname]
    return own or [d for _f, d in found]


def _own_returns(fn):
    """The returns of fn itself, not of functions defined inside it."""
    found, stack = [], list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(n, ast.Return):
            found.append(n)
        stack.extend(ast.iter_child_nodes(n))
    return found


def _is_constant(v):
    if v is None or (isinstance(v, ast.Constant) and v.value in (True, False, None)):
        return True
    return isinstance(v, ast.Attribute) and v.attr in ('SOURCE_REMOVE', 'SOURCE_CONTINUE')


def _call_name(func):
    return func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else None)


def _safe_value(v, fname, defs, seen):
    if _is_constant(v) or isinstance(v, ast.Compare):
        return True
    if isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not):
        return True
    if isinstance(v, ast.IfExp):
        return (_safe_value(v.body, fname, defs, seen)
                and _safe_value(v.orelse, fname, defs, seen))
    if isinstance(v, ast.Call):
        name = _call_name(v.func)
        if name in ('bool', 'int') and len(v.args) == 1:
            return _safe_value(v.args[0], fname, defs, seen)
        # A hand-off to another app function: that one must keep the rule.
        fns = _lookup(name, fname, defs)
        if fns:
            return _safe_function(name, fns, defs, seen)
    return False


def _safe_function(name, fns, defs, seen):
    if name in seen:
        return True
    seen = seen | {name}
    files = {id(d): f for f, d in defs.get(name, [])}
    return all(_safe_value(r.value, files[id(fn)], defs, seen)
               for fn in fns for r in _own_returns(fn))


def _callback(call):
    """The callback argument: idle_add(cb, …) or idle_add(priority, cb, …),
    timeout_add(ms, cb, …)."""
    args = call.args
    if call.func.attr == 'idle_add':
        first = args[0] if args else None
        if isinstance(first, (ast.Lambda, ast.Name)) or (
                isinstance(first, ast.Attribute) and not first.attr.startswith('PRIORITY')):
            return first
        return args[1] if len(args) > 1 else None
    return args[1] if len(args) > 1 else None


def _unsafe(trees):
    defs = _defs(trees)
    bad = []
    for fname, tree in trees.items():
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ADDERS):
                continue
            cb = _callback(n)
            where = f'{fname}:{n.lineno}'
            if isinstance(cb, ast.Lambda):
                b = cb.body
                ends = (_is_constant(b)
                        or (isinstance(b, ast.Subscript) and isinstance(b.value, ast.Tuple)
                            and _is_constant(b.value.elts[-1])))
                if not ends:
                    bad.append(f'{where}: {ast.unparse(cb)}')
                continue
            name = _call_name(cb) if cb is not None else None
            fns = _lookup(name, fname, defs)
            # A name the app does not define is GTK's own (unparent, …).
            if fns and not _safe_function(name, fns, defs, frozenset()):
                bad.append(f'{where}: {name} may return a true value')
    return bad


def test_every_callback_says_when_it_stops():
    assert _unsafe(_trees()) == []


def test_the_check_catches_the_picker_bug():
    tree = ast.parse(
        'class P:\n'
        '    def show(self):\n'
        '        GLib.idle_add(lambda: (row and row.grab_focus()) or False)\n'
        '        GLib.idle_add(lambda: self.go() or GLib.SOURCE_REMOVE)\n'
        '        GLib.timeout_add(50, self._tick)\n'
        '        GLib.idle_add(lambda: (self.go(), GLib.SOURCE_REMOVE)[1])\n'
        '        GLib.idle_add(self._done)\n'
        '    def _tick(self):\n'
        '        return self.widget\n'
        '    def _done(self):\n'
        '        return self._tries < 3\n')
    found = _unsafe({'p.py': tree})
    assert [f.split(':')[1] for f in found] == ['3', '4', '5']
