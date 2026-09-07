---
name: guarding-destructive-operations
description: Add and review preconditions on operations that delete, overwrite, rewrite history, or resolve a caller-supplied name to a filesystem path — refusing instead of warning, placing the guard ahead of the first mutation, structural classification rather than string-prefix matching, name validation plus resolved-path containment as two independent checks, why a guard on the destructive path is invisible to the dry-run, and mutation-testing each half separately. Use when writing or reviewing a `--rebuild`/`--reset`/`--purge` command, a bulk delete, a history rewrite, an `rm -rf`-shaped step, or any code that turns an argument into a file path.
---

# Guarding Destructive Operations

Some operations have no undo: an orphan-branch rewrite, a recursive delete of
every tracked file, an overwrite of a stored artifact, a `DROP`/`purge` path. The
implementation is usually short and usually correct *for the setup its author had
in mind*. The bug is never the deletion itself — it is that nothing checked
whether the target was the thing the author imagined.

Two shapes recur, and they take the same fix:

- **Blast radius.** The operation is correct only in a dedicated, single-purpose
  target and is catastrophic in a mixed one.
- **Boundary escape.** A caller-supplied name is joined onto a base directory and
  lands outside it.

## Refuse; don't warn, and don't add an override

A destructive operation that discovers its precondition is violated should return
an error and change nothing. A warning is read by nobody, and a `--force` escape
hatch turns the guard into documentation.

```go
// A rebuild that recreates history does `checkout --orphan` then
// `rm -rf --ignore-unmatch .`, keeping only the state files it rewrites.
// That is correct in a dedicated mirror repository whose ONLY tracked content
// is `.state/`. Run it where source code also lives and the new branch loses
// the source code.
func (e *Engine) rebuild() error {
    if err := e.ensureDedicatedRepo(); err != nil {
        return err   // nothing mutated yet
    }
    ...
}
```

The honest justification for having no override flag: there is no situation where
the operator wants this command to delete unrelated tracked files. If a real one
appears later, that is a separate, differently-named command — not a boolean on
this one.

## Put the guard ahead of the first mutation

"Refuses" is only true if the refusal happens before anything has changed.
Walk the function and find the *first* statement with an effect — it is often not
the obvious deletion. In-memory state clearing, a branch checkout, and a
read-then-rewrite of the very files you are preserving all count.

```go
// Order that makes the refusal safe:
//   1. reject detached HEAD / ambiguous state
//   2. ensureDedicatedRepo()          <-- the new guard, nothing mutated yet
//   3. read the state files to preserve
//   4. CheckoutOrphan()
//   5. RemoveAllTrackedFiles()
//   6. ClearAllProgressCounts()
```

Steps 3-6 are all mutations of something (3 is not, but it is where the "what to
preserve" snapshot is taken, and a guard after it has already committed you to a
shape). Land the guard at 2 and a rejected run leaves the working tree byte-identical.

Also refuse *ambiguous* state before rewriting it. A history rewrite that assumes
a named branch should reject detached HEAD up front rather than silently
recreating the wrong ref.

## Classify structurally, not by string prefix

The guard needs to answer "is every tracked path inside the directory this
command owns?". A `HasPrefix`/`startswith` on the bare directory name is the
wrong answer and looks right in every test you would think to write.

```go
// Bad — admits `.state-backup/notes.md` and `.stateful.txt`, so a repository
// full of unrelated content passes the guard and gets deleted.
func owned(path string) bool {
    return strings.HasPrefix(path, ".state")
}

// Good — the directory itself, or something genuinely under it.
func owned(path string) bool {
    return path == ".state" || strings.HasPrefix(path, ".state/")
}
```

The same distinction in Python is `Path(p) == base or base in Path(p).parents`,
not `p.startswith(str(base))`. Any time a check compares paths as strings, ask
what a sibling with a longer name does to it.

## Name validation and resolved containment are two checks, not one

When a public argument selects a file — a baseline name, a template id, a report
slug — do both, in this order:

```python
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

def _validate_name(name: str) -> str:
    if ".." in name or not NAME_RE.match(name):
        raise ValueError(f"invalid name: {name!r}")
    return name

def _resolve(name: str, base: Path) -> Path:
    candidate = (base / f"{_validate_name(name)}.json").resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise ValueError(f"name escapes {base}: {name!r}")
    return candidate
```

The containment half is **not** redundant with the regex. The regex stops `..`
segments and absolute paths; only the `resolve()` + containment check stops a
*symlink placed inside the directory* that points out of it — a name matching
`^[A-Za-z0-9]` all the way through can still resolve anywhere. Route every entry
point through both: the loader, the saver, and any path-building helper a public
method still calls directly. A single unrouted helper reinstates the whole hole.

Without this, an implicit suffix (`name + ".json"`) plus an absolute-path
argument reads any file on disk whose name happens to end in that suffix.

## A guard on the destructive path is invisible to the preview

If the real run reaches the guard but `--dry-run` short-circuits earlier, the
preview cheerfully describes an operation the real run will refuse. That is a
defensible design — the destructive path is the one that must be safe — but be
explicit about it:

- The preview will show a full rebuild in a repository where the rebuild is
  forbidden. Only the real invocation errors.
- Anything meant to warn the operator *earlier* has to live in the preview stage
  or the CLI argument-validation layer, duplicated deliberately, not moved.

Say which one you chose in the PR description; a reviewer cannot tell from the
diff whether the dry-run gap is intentional.

## Know what the caller does with your refusal

Tightening validation only helps if the new error reaches somebody. A broad
`except Exception` two frames up will turn a hard refusal into an ordinary
result shape:

```python
try:
    features = self._load(baseline)
except Exception as e:                       # already there, catches your ValueError
    return {"error": f"Analysis failed: {e}", "features": {}, "flags": {...}}
```

This is often *fine* — an API boundary that never raises is a real contract, and
the refusal surfaces as a normal error-shaped response rather than a protocol
error. But check it deliberately: if that shape is what your caller sees, the
integration test asserts on `result["error"]`, not on `pytest.raises`.

## Testing

- **Mutate each half separately.** Neuter only the regex and confirm a `..`
  fixture fails; neuter only the containment check and confirm a *symlink*
  fixture fails. One combined test passes with either half deleted and proves
  neither.
- **Write the sibling-name fixture explicitly.** A test whose repository tracks
  `.state/data.json` passes against `HasPrefix(path, ".state")` too. The test
  that separates the implementations tracks `.state-backup/old.json` and asserts
  the operation is refused.
- **Assert nothing was mutated on refusal**, not just that an error came back:
  the branch is unchanged, the tracked file list is unchanged, the in-memory
  progress counters are unchanged. That is the actual claim.
- **Existing fixtures become the rejected shape.** Older tests for the
  destructive path were often built loosely — a repository tracking `app.txt`
  alongside the state directory, because nothing cared. After the guard, such a
  test no longer reaches the code it was written to cover; it now exercises the
  refusal. Tighten those fixtures to the allowed shape and add the refusal case
  as a *new* test, or you silently lose coverage of the destructive path.
- **Reproduce the failure with the narrowest hook.** When you need one specific
  operation to fail in order to test the recovery path, target it precisely — a
  blanket hook that rejects every operation of that kind aborts the run earlier
  than the path you were trying to reach, and the test proves something else.

## Checklist

- [ ] Every irreversible operation states its precondition in code, not in a doc
- [ ] Violation returns an error; no `--force`, no warn-and-continue
- [ ] The guard runs before the first statement with an effect
- [ ] Ambiguous state (detached HEAD, missing target, multiple candidates) rejected up front
- [ ] Path/ownership classification is structural, never a bare string prefix
- [ ] Caller-supplied names are validated *and* resolved-path contained
- [ ] Every entry point routes through both checks, including internal helpers
- [ ] The dry-run/preview gap is intentional and stated
- [ ] Tests mutate each half of the guard independently
- [ ] A sibling-name (`x-backup/`) and a symlink fixture both exist
- [ ] Refusal tests assert the target is unchanged, not just that an error was raised

## Note for this repository (ffmpeg-skill)

This repo's actual exposure is much narrower than the examples above — there is
no `--rebuild`/`--purge`-shaped command, no history rewriting, and "Keep
originals" is already a stated design principle (`README.md` design principle
#9: no tool overwrites its input; a test hashes every input after every run,
see `tests/test_all.py`/`tests/test_contract.py`'s input-hash checks). The
closest analogue is `-o`/output-path handling: every tool takes a
caller-supplied output path and `ffmpeg_base()` always passes `-y` (overwrite
without prompting) — there is no confirmation step before an existing file at
that path is silently replaced. Since this is a local CLI a human or agent
invokes directly (not a server resolving untrusted network input against a
base directory), the "boundary escape" half of this skill is low-stakes here;
the "refuse before the first mutation" and "existing input-hash tests still
prove nothing was touched" halves are the parts that actually apply.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
