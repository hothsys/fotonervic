# Roadmap

Planned work for Foto Nerve Shatter. Items here graduate to GitHub issues when work starts.

## Engineering health

- **Make testing comprehensive.** CI today lints only (ruff, biome) and never executes the Python code, so a dependency bump like the numpy 1.x to 2.x upgrade (#42) can merge with zero runtime verification. Add unit tests covering the backend (blur check, recovery, EXIF) and a CI workflow that runs the test suite on every PR and push to main.
