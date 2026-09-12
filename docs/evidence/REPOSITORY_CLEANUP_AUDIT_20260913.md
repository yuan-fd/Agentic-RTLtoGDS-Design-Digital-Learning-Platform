# Repository cleanup audit — 2026-09-13

The working tree is clean on `feat/llm-teaching-platform`. Tracked SQLite files
under `docs/evidence/` are frozen acceptance fixtures, not live runtime state;
they are retained for reproducibility. Live databases and run directories are
ignored under `var/` and `runs/`.

The API README labels legacy import and historical v2 routes explicitly. They
remain read-only or fail closed, so removing them now would risk breaking old
evidence consumers. No untracked generated files or accidental source changes
are present in the current tree.

Environment diagnosis passes and the full regression suite is green. Remaining
cleanup is a deliberate migration task for the legacy compatibility surface,
not an unreviewed deletion.
