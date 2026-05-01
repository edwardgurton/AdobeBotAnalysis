## 16. Implementation Orchestration

### 16.1 Why This Section Exists

Sections 1–15 describe the *target* — what the tool looks like once it is built. This section describes *how to build it across multiple work sessions*, where each session may be subject to context-window or plan-tier limits and the build will not finish in one sitting.

The runtime state-tracking machinery in §6 (SQLite request DB, job history JSONL, config archival) tracks what the tool *does once it exists*. It does not track the build process itself. That is the gap this section fills.

The build is orchestrated through three plain files in the repo root:

| File | Purpose | Updated |
|---|---|---|
| `CLAUDE.md` | Persistent context for Claude Code: what the project is, where the plan lives, how to behave each session. | Rarely (when conventions change) |
| `IMPLEMENTATION_STATUS.md` | The live progress tracker — every step from §13 with a status, dates, and notes. | At least once per session |
| Git commit history | The immutable record of what code actually changed when. | Per step (or sub-step) |

`CLAUDE.md` and `IMPLEMENTATION_STATUS.md` are committed to the repo. Together they answer two questions: *"what is this project?"* (CLAUDE.md) and *"where am I in building it?"* (IMPLEMENTATION_STATUS.md).

### 16.2 The Status File

`IMPLEMENTATION_STATUS.md` is pre-populated with every numbered step from §13 (Steps 0 through 19, including 0.5 and 0.75). Each step has:

- **Status**: `☐ todo` / `🔄 in-progress` / `✅ done` / `⚠️ blocked`
- **Started** / **Completed**: ISO dates
- **Validation**: a one-line note recording how the step's validation criterion (from §13) was satisfied
- **Notes**: any deviations from plan, deferred items, or things to revisit

The file also contains a **Current State** block at the top — what step is active right now, what the next concrete action is, and any in-flight work that hasn't been committed yet — and a **Session Log** at the bottom, append-only, one entry per session.

The Current State block is the single most important element. It is what a fresh session reads first and what tells it where to resume. It must always reflect the actual state of the working tree at the moment the session ended.

### 16.3 Session Lifecycle

Every session follows the same four-step protocol. The protocol exists because the alternative — re-deriving "where are we?" from the plan, the codebase, and memory — burns context and produces inconsistent restart points.

**1. Open.** Read `IMPLEMENTATION_STATUS.md` end-to-end. Read the Current State block carefully. If the next action references a specific section of the plan (e.g. "implement §3.2 `state_manager.py`"), read only that section, not the whole plan.

**2. Work.** Execute the next action. If a step is large, break it into sub-steps and commit each one separately. Don't try to land a whole §13 step in one commit unless it's genuinely small.

**3. Checkpoint.** Whenever a sub-step is done, commit it. Commit messages follow the format `Step N.M: <one-line description>`. Tests/validation criteria from §13 are run as part of the checkpoint.

**4. Close.** Before ending the session, update `IMPLEMENTATION_STATUS.md`:
- Mark completed steps `✅ done` with completion date and validation note
- Update the Current State block to reflect the new resume point
- Add a Session Log entry: date, what was done, what's left in flight, the very next concrete action
- Commit the status file change with message `status: end of session <date>`

The Close step is non-negotiable. A session that runs out of context mid-work is fine — what is *not* fine is a session that ends without leaving a clean handoff. If you sense the session is filling up, stop coding and do the Close step while you still have room.

### 16.4 Git as the Immutable Trail

`IMPLEMENTATION_STATUS.md` is the human-readable view of progress. `git log` is the source of truth. If the two ever disagree, `git log` wins and the status file gets corrected.

Conventions:

- One step per branch is overkill for this project; work directly on `main` (or a single long-lived `build` branch) and commit per sub-step.
- Commit message format: `Step <N.M>: <imperative one-line>`. Examples: `Step 1: Project scaffold + Pydantic schemas`, `Step 7.2: SQLite state manager — canonical_request_id`, `Step 9.3: Port bot_investigation transform`.
- The Session Log entry for each session should reference the commit SHA range it covers, so you can `git log <start>..<end>` to see exactly what shipped.

### 16.5 Running This with Claude Code

[Claude Code](https://docs.claude.com/en/docs/claude-code/overview) is Anthropic's terminal-based agentic coding tool. It is the right tool for executing this plan because (a) it operates directly on the repo, (b) it reads `CLAUDE.md` automatically at the start of every session, and (c) it handles the read-files / edit-files / run-tests loop without manual copy-paste. A Pro plan covers Claude Code usage.

#### One-time setup

1. Install Claude Code following the instructions at <https://docs.claude.com/en/docs/claude-code/setup>. The native installer is recommended; npm install is deprecated.
2. From the repo root, run `claude` to verify it starts.
3. Confirm `CLAUDE.md`, `IMPLEMENTATION_STATUS.md`, and the technical plan (`docs/Adobe_Downloader_Technical_Plan.md`) all exist in the repo and are committed.

#### Per-session workflow

Open a terminal in the repo root and run `claude`. The first prompt of every session is the same:

> Read `IMPLEMENTATION_STATUS.md`, then tell me where we are and what the next concrete action is. Do not start coding yet.

Claude Code will read the status file (and `CLAUDE.md` automatically) and report the resume point. Confirm the next action is what you expected, then say "go." Claude executes the work, runs the validation criteria, commits per sub-step, and updates the status file.

When you sense the session is running long, end with:

> Wrap up — finish the current sub-step if you're close, otherwise stop cleanly. Update IMPLEMENTATION_STATUS.md, write a Session Log entry, and commit. Tell me what's left in flight and what to do first next session.

The next session opens with the same first prompt and the loop continues.

#### What to put in CLAUDE.md vs the plan vs the status file

These three files have non-overlapping jobs and the boundaries matter:

- **`CLAUDE.md`** — short, stable, answers "what kind of project is this and how should I behave in every session." Coding conventions (Python 3.12+, minimal deps from §1.8), the session protocol, where to find the plan and status. Target under 100 lines. Doesn't change between sessions.
- **The plan** (`docs/Adobe_Downloader_Technical_Plan.md`) — long, stable, the *spec*. Read on demand, not by default. Claude Code only loads the section relevant to the current step.
- **`IMPLEMENTATION_STATUS.md`** — short-to-medium, *changes every session*, the *log*. Read by default at session start. The state of the build.

If a piece of information would be useful in every session forever, it goes in `CLAUDE.md`. If it would be useful only when working on a specific step, it stays in the plan. If it describes what's been done or what's next, it goes in the status file.

### 16.6 What "Done" Looks Like

The build is complete when:

- Every step in `IMPLEMENTATION_STATUS.md` is marked `✅ done`.
- Step 19 (end-to-end validation) has passed against real production runs.
- The status file's Current State block reads "Build complete — see Session Log for full history."

At that point `IMPLEMENTATION_STATUS.md` becomes a historical record. It can be moved to `docs/build_history.md` if desired, or left in place as a forever-monument to the migration.

---
