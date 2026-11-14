#!/bin/sh
# Eval 25: run each agent prompt once, headless, with the skill as it ships.
#   sh evals/run_agents_25.sh RUN_DIR [MODEL]
# Stages fixtures (write_fixtures.py), installs the skill into RUN_DIR/<id>/.claude/skills/
# with the npm installer (bin/install.js --dir), runs `claude -p` in that folder and saves the
# stream-json log to RUN_DIR/<id>/transcript.jsonl. Grade with evals/grade_runs_25.py RUN_DIR.
#
# The skill folder is an installed copy, not a link to this checkout (#467 A271, A274): a link
# gave the agent the whole repository -- this folder's prompts and answer keys, tests, the
# maintainer notes -- as "the skill", and, with every permission check off, a run that edited
# a file under it edited the tracked tree. The copy is the set `npx ffmpeg-skill` installs.
# The agent still runs as the caller, with the caller's HOME (`claude -p` reads its sign-in
# from there) and environment, so the checkout's state is taken before and after each run:
# `git status`, the content diff of tracked files against HEAD (a file already modified keeps
# its ` M` line when a run edits it again), the hash of every untracked file and HEAD (a run
# that commits its edit). A snapshot that cannot be taken stops the script (exit 3). A run that
# changed it is named in RUN_DIR/<id>/.tree_changed, and the script exits 1. A RUN_DIR inside
# the checkout must be git-ignored: the run's own files would read as a change to it.
set -eu
RUN=$1
MODEL=${2:-sonnet}
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
made=""
[ -d "$RUN" ] || { mkdir -p "$RUN"; made=1; }
RUN_ABS=$(cd "$RUN" && pwd -P)
case "$RUN_ABS/" in
  "$REPO"/*)
    if ! git -C "$REPO" check-ignore -q "$RUN_ABS"; then
      [ -z "$made" ] || rmdir "$RUN" 2>/dev/null || true
      echo "RUN_DIR $RUN_ABS is inside the checkout at $REPO and not git-ignored: the run's own files would read as a change to the checkout; use a folder outside it or an ignored one" >&2
      exit 2
    fi ;;
esac
tree_state() {
  # HEAD first: a run that commits its edit leaves `git status` clean and the diff against the
  # new HEAD empty. A command that fails is a failure of the snapshot, never a state to compare
  git -C "$REPO" rev-parse HEAD 2>/dev/null &&
    git -C "$REPO" status --porcelain=v1 --untracked-files=all 2>/dev/null &&
    git -C "$REPO" diff --binary --no-ext-diff HEAD 2>/dev/null || return 1
  # the list goes through a file, not a pipe: a pipeline's status is its last command's, so a
  # failed `ls-files` in front of an xargs with nothing to do read as a clean, empty list
  list=$(mktemp) || return 1
  if git -C "$REPO" ls-files -z --others --exclude-standard > "$list" 2>/dev/null &&
     (cd "$REPO" && xargs -0 git hash-object -- < "$list" 2>/dev/null); then
    rm -f "$list"
  else
    rm -f "$list"
    return 1
  fi
}
no_state() {
  echo "cannot read the state of the checkout at $REPO ($1 run $2): a run it cannot watch is not started or not reported as clean" >&2
  exit 3
}
python3 "$REPO/evals/write_fixtures.py" "$RUN" --all "$REPO/evals/agent_prompts_25.json" >/dev/null
changed=""
for id in $(python3 -c 'import json,sys; print(" ".join(p["id"] for p in json.load(open(sys.argv[1]))))' "$REPO/evals/agent_prompts_25.json"); do
  d="$RUN/$id"
  mkdir -p "$d/.claude/skills"
  rm -rf "$d/.claude/skills/ffmpeg-skill"
  node "$REPO/bin/install.js" --dir "$d/.claude/skills" >/dev/null
  ls "$d" > "$d/.before"
  prompt=$(python3 -c 'import json,sys; print([p["prompt"] for p in json.load(open(sys.argv[1])) if p["id"]==sys.argv[2]][0])' "$REPO/evals/agent_prompts_25.json" "$id")
  before=$(tree_state) || no_state before "$id"
  (cd "$d" && claude -p "$prompt" --model "$MODEL" --output-format stream-json --verbose \
      --permission-mode bypassPermissions --max-turns 30 > transcript.jsonl 2> stderr.txt) || true
  after=$(tree_state) || no_state after "$id"
  ls "$d" > "$d/.after"
  rm -f "$d/.tree_changed"
  if [ "$before" != "$after" ]; then
    printf '%s\n' "$after" > "$d/.tree_changed"
    changed="$changed $id"
  fi
done
if [ -n "$changed" ]; then
  echo "the checkout at $REPO changed during:$changed (its state in RUN_DIR/<id>/.tree_changed)" >&2
  exit 1
fi
