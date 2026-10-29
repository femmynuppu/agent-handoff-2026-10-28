# Captured local OMP changes

Source HEAD at capture: `1eee04c91497f756d77df20abd169b7c3896a88d`, `feat/telegram-bridge` in the existing `enyonee/oh-my-pi` checkout.

- `packages/coding-agent/src/commands/telegram.ts`: local-only `status` branch for config sanity, `pair` branch using the source's `Settings`, per-bot host lock, pairing API, persisting only the chat/user IDs to the configured OMP settings, release/response handling for success/refusal/timeout/cancellation. Existing execution entrypoint continues after this command branch.
- `.omp/skills/property-verifier/SKILL.md`: new local skill file copied from the OMP source worktree.
- Several unrelated upstream test fixtures containing realistic credential-shaped values and the reusable `claude-trace-cli.ts` test MITM key were withheld from the copy; consult the upstream source if those unrelated test paths are needed.
This export has no Git history/remote, and no push to original/upstream OMP repositories is implied. Original worktree was not changed.
