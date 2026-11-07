#!/usr/bin/env bash
# 100-turn lean pass: each turn, agy (Gemini 4 Argon High, Exa MCP available)
# strips one piece of NouGenCode to be leaner/faster WITHOUT losing capability.
# Gate per turn: full test suite green AND passing-test count never drops.
# A failed gate reverts the turn. Kept turns are committed, logged to
# docs/lean-pass.md, and captured as a shard.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SHARDS="$HOME/The Observatory/NouGen/nougenshards"
TURNS="${TURNS:-100}"
MODEL="${MODEL:-gemini-4-argon-high}"
LOG="$HOME/.nougen/state/lean_loop.log"
LEDGER="$REPO/docs/lean-pass.md"
cd "$REPO" || exit 1
mkdir -p "$(dirname "$LOG")"
if [ ! -f "$LEDGER" ]; then
  printf '# NouGenCode lean pass (agy %s, 100 turns)\n\nEach kept turn: one cut, tests green, passing count never lower.\n\n' "$MODEL" > "$LEDGER"
  git add "$LEDGER" && git commit -q -m "Start the lean-pass ledger" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
fi

passed() { uv run --quiet --with pytest pytest -q -p no:cacheprovider 2>&1 | grep -Eo '[0-9]+ passed' | grep -Eo '[0-9]+' || echo 0; }
fails()  { uv run --quiet --with pytest pytest -q -p no:cacheprovider 2>&1 | grep -Eq '[0-9]+ (failed|error)'; }

BASE=$(passed); echo "$(date '+%F %I:%M %p') start base_passed=$BASE model=$MODEL" >> "$LOG"
for i in $(seq 1 "$TURNS"); do
  PROMPT="You are on turn $i of $TURNS of a lean pass over the NouGenCode repo at $REPO (Python, src/nougencode, tests/).
Goal: make ONE focused change that makes the code leaner, meaner and lower-latency WITHOUT losing any capability: delete dead code, collapse duplication, cut needless imports or startup work, lazy-load heavy modules, simplify hot paths. Read docs/lean-pass.md first and do not repeat or undo a past turn. Use the exa MCP for prior art when a pattern is unclear.
Rules: never delete or weaken tests; never change public behaviour; keep the diff small. Do not commit or push. Verify with: uv run --quiet --with pytest pytest -q
End your reply with exactly one line: FINDING: <one sentence: what you cut, why it is safe, lines saved or latency gained>"
  OUT=$(agy --print-timeout 25m --dangerously-skip-permissions --model "$MODEL" --add-dir "$REPO" -p "$PROMPT" 2>&1)
  printf '%s\n' "$OUT" | tail -40 > "$HOME/.nougen/state/lean_turn_$i.out"
  FINDING=$(printf '%s\n' "$OUT" | grep -E '^FINDING:' | tail -1 | cut -c10-)
  if printf '%s' "$OUT" | grep -q 'AGY_ERROR\|credits balance is too low'; then
    echo "$(date '+%F %I:%M %p') turn $i: agy failed, stopping" >> "$LOG"; git checkout -q -- . && git clean -qfd -- src tests; break
  fi
  if [ -z "$FINDING" ] || git diff --quiet -- src; then
    git checkout -q -- . && git clean -qfd -- src tests
    echo "$(date '+%F %I:%M %p') turn $i: no change" >> "$LOG"; continue
  fi
  NOW=$(passed)
  if fails || [ "$NOW" -lt "$BASE" ]; then
    git checkout -q -- . && git clean -qfd -- src tests
    echo "$(date '+%F %I:%M %p') turn $i: REVERTED (passed=$NOW base=$BASE) $FINDING" >> "$LOG"; continue
  fi
  BASE=$NOW
  SAVED=$(git diff --numstat -- src | awk '{d+=$2-$1} END{print d+0}')
  printf -- '- **Turn %s** (%s lines net removed): %s\n' "$i" "$SAVED" "${FINDING:-no finding line}" >> "$LEDGER"
  git add -A src tests docs && git commit -q -m "lean turn $i: ${FINDING:0:60}" -m "${FINDING}" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  (cd "$SHARDS" && ./.venv/bin/nougen add --tags "nougencode,lean-pass,agy" --domain nougencode \
     "NouGenCode lean pass turn $i ($(git -C "$REPO" rev-parse --short HEAD), $SAVED lines net removed, $NOW tests green): $FINDING" >/dev/null 2>&1)
  echo "$(date '+%F %I:%M %p') turn $i: KEPT $(git rev-parse --short HEAD) saved=$SAVED passed=$NOW" >> "$LOG"
done
echo "$(date '+%F %I:%M %p') done: $(git rev-list --count origin/main..HEAD) commits, $(find src -name '*.py' | xargs cat | wc -l) src lines" >> "$LOG"
