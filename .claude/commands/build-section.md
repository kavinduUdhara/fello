Build the Fello frontend section specified in $ARGUMENTS.

Steps:
1. Read CLAUDE.md and identify which routes are in this section.
2. Spawn the ui-builder subagent to build all pages and components for this section.
3. After ui-builder completes, spawn the security-auditor subagent to check the new code.
4. Fix any CRITICAL issues reported by the auditor.
5. Spawn the test-runner subagent to run type check and build.
6. Fix any errors reported by test-runner.
7. Report what was built and confirm it passes all checks.

Valid section names: events-dashboard, event-detail, members, settings, chatbot, auth-flow, onboarding
