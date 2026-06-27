Run a type check and fix all errors.

1. Run: `pnpm tsc --noEmit`
2. For each error, read the file, understand the type error, and fix it.
3. Re-run after fixes.
4. Repeat until `pnpm tsc --noEmit` exits with 0 errors.
5. Report: "Type check passes. 0 errors."
