# TOOLS.md — CEO Tools

## Paperclip API (primary coordination layer)

All coordination happens via the Paperclip REST API at `http://localhost:3100/api`.
Always include `X-Paperclip-Run-Id` header on mutating calls.

### Issues
- `GET /api/companies/{companyId}/issues` — list issues, filter by `assigneeAgentId`, `status`, `projectId`
- `POST /api/companies/{companyId}/issues` — create issue (always set `projectId`, `assigneeAgentId`)
- `PATCH /api/issues/{id}` — update issue (status, assignee, comment)
- `POST /api/issues/{id}/checkout` — checkout before working; 409 = already claimed
- `POST /api/issues/{id}/comments` — post comment

### Routines
- `GET /api/companies/{companyId}/routines` — list all routines
- Heartbeat routines fire automatically — CEO does not self-schedule

### Agents
- `GET /api/companies/{companyId}/agents` — list agents and their IDs
- `GET /api/agents/me` — confirm own identity, budget, chain of command

## Company Context

- **Company:** Quant Zero
- **Company ID:** `2b92869b-8fc2-4eb8-8e23-910bc1b0a626`
- **Project:** quant-zero
- **Project ID:** `a6e8443a-76b1-4156-959b-3c18a270576a`
- **Paperclip URL:** `http://localhost:3100`

## Director Agent IDs

| Agent | ID |
|---|---|
| Research Director | `98976970-d209-4422-8a45-179ffc61f19e` |
| Engineering Director | `48b67b44-5371-4238-8d7a-077015a676fd` |
| Risk Director | `f18a5b70-f25c-4e91-a2e0-eb364df013a4` |
| Portfolio Monitor | `1bdfecf4-4dd7-46be-88f8-7b037b54c4be` |
| Overfit Detector | `1da4c9ad-ecce-4c7c-bcf0-9113cc0e7aa4` |
| Alpha Research | `478676b6-ec22-4ff7-9520-6484354ea3e8` |
| Market Regime | `1f739499-7214-4cb8-88c8-998a86d5b10e` |
| Strategy Coder | `d3811c7b-384e-4a9b-993c-f93a8e8284a2` |
| Backtest Runner | `6824d256-574e-48a4-a1c8-9b899017667a` |

## Git (quant-zero repo)

- Repo path in container: `/repos/quant-zero`
- GitHub: `https://github.com/marcohwlam/quant-zero`
- Push: set remote URL with `GH_TOKEN` env var before pushing
  ```bash
  git remote set-url origin https://${GH_TOKEN}@github.com/marcohwlam/quant-zero.git
  ```

## File Conventions

- Heartbeat reports: `docs/heartbeats/<domain>/YYYY-MM-DD.md`
- Templates: `docs/templates/director-heartbeat-template.md`
- Gate 1 criteria (CEO-locked): `criteria.md`
- Mission / Risk Constitution: `docs/mission_statement.md`
