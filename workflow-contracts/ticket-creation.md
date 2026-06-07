# Ticket Creation Contract

## Rule

All agents MUST set `projectId` when creating issues. Never create project-less (`projectId=null`) tickets.

## Implementation

1. Read the `PAPERCLIP_PROJECT_ID` environment variable — Paperclip injects it into every agent run.
2. Set `projectId = $PAPERCLIP_PROJECT_ID` on every issue you create.
3. If `$PAPERCLIP_PROJECT_ID` is empty or unset, fall back to the hardcoded project ID:
   `a6e8443a-76b1-4156-959b-3c18a270576a` (quant-zero).

## Non-negotiable

A ticket with `projectId=null` is a policy violation. No exceptions.
