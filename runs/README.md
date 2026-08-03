# runs/ — one directory per quality-loop cycle

Each cycle writes `runs/<tag>/`:

    report.json   machine-readable: variant, per-ref status, metrics, identity
    report.md     the human table (paste into notes / commit messages)
    out_<i>.png   final render per yardstick reference
    ref_<name>    the reference pixels used for metric comparison
    zoom/         200% contact sheets, when generated

Tags are descriptive and permanent: `v6-baseline`, `grain-transplant-r3`,
`detaildaemon-035`. Never overwrite a tag — a rejected cycle is evidence and
stays on disk.

Verdicts live in report.md. Write the reason for a REJECT as plainly as the
reason for an ACCEPT; the queue in ../docs/QUALITY_LOOP.md is re-ranked from
what these files actually showed, not from what was expected.
