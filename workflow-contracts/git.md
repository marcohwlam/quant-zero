# Git Workflow Contract (CEO-locked)

The single source of truth for git workflow across ALL Quant Zero agents.
No agent keeps its own copy. Every agent's AGENTS.md references this file.

## When to use

After completing any ticket that produces file changes (code, reports, configs,
heartbeats, knowledge base updates, agent definitions).

## Steps

1. Create a feature branch named after the ticket:
   ```bash
   git checkout -b feat/QUA-<N>-short-description
   ```

2. Stage and commit all changed files:
   ```bash
   git add <changed files>
   git commit -m "feat(QUA-<N>): <short description>

   Co-Authored-By: Paperclip <noreply@paperclip.ing>"
   ```

3. Push the branch to origin:
   ```bash
   git push -u origin feat/QUA-<N>-short-description
   ```

4. Create a PR using the GitHub CLI:
   ```bash
   gh pr create --title "feat(QUA-<N>): <short description>" --body "Closes QUA-<N>"
   ```

5. Post the PR URL as a comment on the Paperclip ticket and notify your manager.

6. Auto-merge the PR immediately after creation:
   ```bash
   gh pr merge --merge --auto
   ```

## Rules

- Never commit `.env` files, secrets, or credentials.
- Never force-push to `main`.
- Always include `Co-Authored-By: Paperclip <noreply@paperclip.ing>` in every commit.
- One feature branch per ticket. Do not commit unrelated work onto another ticket's branch.
