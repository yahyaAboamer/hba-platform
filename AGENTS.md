# Agent instructions — Codex, Claude, and anything else

**Read these two, in this order, before touching anything:**

1. **[`docs/RULES.md`](docs/RULES.md)** — how the platform must behave. The
   single shared source. Every agent reads the same file, so no two of us can
   be working from different money rules.
2. **[`CLAUDE.md`](CLAUDE.md)** — how to work in this repository: the
   verification commands, the branch discipline, the browser harness, what is
   superseded and by what. It is named for one tool and applies to all of
   them; renaming it would break the tooling that loads it automatically.

Then **[`docs/plans/2026-09-24-continuation-handoff.md`](docs/plans/2026-09-24-continuation-handoff.md)**
for where the work actually is — branch, commit, next task.

## Why this file is three links and nothing else

Because the alternative is two sets of instructions that drift. This
repository has already been bitten by exactly that: a handoff said *"pending
orders are not counted by the live rule"* while `CLAUDE.md` said *"a pending
order counts"*, and both were sitting in the tree at once, eight days apart.
One of them was wrong for eight days and nothing noticed.

So: **if you find yourself wanting to write a rule down here, it belongs in
`docs/RULES.md`.** If you want to write down a command or a habit, it belongs
in `CLAUDE.md`. Nothing but pointers lives here.

## The three standing restrictions, so they are unmissable

They are in `docs/RULES.md` in full. In one line each:

- **No merge, no deployment.** The repair stays on its branch until the owner
  says otherwise.
- **Historical finalisation stays locked** behind
  `HISTORICAL_FINALISATION_UNLOCKED` until HBA supplies and verifies what
  `docs/repair/HISTORICAL-INFORMATION-NEEDED.md` lists.
- **No destructive fixture against staging or production**, and do not defeat
  the guard that enforces it.
