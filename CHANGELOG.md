# Muse Multi Studio — Changelog

## v0.2.0 (2026-10-17) — Integrity & Recovery

- Validate generated images (Pillow full decode) and MP4 structure; optional ffprobe video decode.
- Atomic publication of all media for one job; rollback staged files on failure.
- Preserve gallery metadata and output after deleting a job; migrate legacy SQLite assets.
- Persist worker count (1–8) and prevent retried requests from unintentional re-billing.
- Distinguish `provider_failed`, `download_failed`, `submitted`, `ambiguous`, `result_ready`.
- Require explicit confirmation for potentially duplicate paid submissions.
- Scope bulk retry to project and skip ambiguous requests.
- Show cancellation pending in task list; project-specific task counters.
- Add `/api/jobs` pagination endpoint; `/api/state` no longer truncates at 1,000 jobs.
- Normalize downloaded image aspect ratio via deterministic center crop.
- Retry transient errors for safe idempotent GET only. Avoid blind replay of paid POST.
- New Windows CI runner build and `--server-only` Windows binary smoke test.

### What is NOT verified

- No real paid fal/OpenAI API keys available to confirm credit consumption and actual generated video.
- No native Windows GUI interaction/E2E test possible in Linux development runtime.
- Windows EXE is built by GitHub Actions on a Windows runner when code is pushed to GitHub; no EXE included in source archive.
- Existing local SQLite remains at `%LOCALAPPDATA%\\MuseMultiStudio`; always back it up before upgrade.
- Crash recovery additionally marks untracked in-flight paid requests as ambiguous instead of automatically resubmitting.
- Regression suite includes real encoded MP4 verification and v0.1.0-to-v0.2.0 migration validation.
