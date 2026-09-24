#!/bin/sh
# Eval 25: run each agent prompt once, headless, with the skill loaded from this checkout.
#   sh evals/run_agents_25.sh RUN_DIR [MODEL]
# Stages fixtures (write_fixtures.py), links the skill in as a project skill under
# RUN_DIR/<id>/.claude/skills/ffmpeg-skill, runs `claude -p` in that folder and saves the
# stream-json log to RUN_DIR/<id>/transcript.jsonl. Grade with evals/grade_runs_25.py RUN_DIR.
set -eu
RUN=$1
MODEL=${2:-sonnet}
REPO=$(cd "$(dirname "$0")/.." && pwd)
python3 "$REPO/evals/write_fixtures.py" "$RUN" --all "$REPO/evals/agent_prompts_25.json" >/dev/null
for id in $(python3 -c 'import json,sys; print(" ".join(p["id"] for p in json.load(open(sys.argv[1]))))' "$REPO/evals/agent_prompts_25.json"); do
  d="$RUN/$id"
  mkdir -p "$d/.claude/skills"
  ln -sfn "$REPO" "$d/.claude/skills/ffmpeg-skill"
  ls "$d" > "$d/.before"
  prompt=$(python3 -c 'import json,sys; print([p["prompt"] for p in json.load(open(sys.argv[1])) if p["id"]==sys.argv[2]][0])' "$REPO/evals/agent_prompts_25.json" "$id")
  (cd "$d" && claude -p "$prompt" --model "$MODEL" --output-format stream-json --verbose \
      --permission-mode bypassPermissions --max-turns 30 > transcript.jsonl 2> stderr.txt) || true
  ls "$d" > "$d/.after"
done
