Run a full security audit of the Fello codebase.

Spawn the security-auditor subagent with this prompt:
"Run a complete security audit of the entire codebase. Check all six categories. Report every finding with file name and line number. Classify each as CRITICAL, WARNING, or PASS."

After the subagent returns, present the full report. For each CRITICAL issue, fix it immediately in the main session.
