# n8n flows

The pipeline exposes a small FastAPI service for n8n. It **drafts and logs only**; no endpoint sends a message.

```bash
export HOSTOP_API_TOKEN=<long random string>      # required; the API refuses to run with the placeholder
uvicorn hostop.api.app:app --port 8000            # HOSTOP_DEMO=1 to run against the SYNTHETIC demo DB
```

Every call sends header `X-HostOp-Token: <HOSTOP_API_TOKEN>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + operator count |
| POST | `/operators/{id}/score` | re-score one operator, returns the explain view with evidence |
| POST | `/operators/{id}/draft` | generate drafts for one operator (status `pending` or `needs_fix`) |
| POST | `/webhooks/reply` | log a reply; auto-suppresses opt-outs; `positive` only if you set it |

---

## Flow 1: New inbound signal -> score -> draft -> human review in Slack

Use when someone adds an operator by hand (event list, referral) and you want it researched the same day.

1. **Trigger: Webhook** (or Google Sheets "Row added"). Payload: `{operator_id}` after you ran
   `hostop discover` / `hostop analyze` for the new row, or the id from the dashboard.
2. **HTTP Request** `POST {{API}}/operators/{{$json.operator_id}}/score`, header `X-HostOp-Token`.
3. **IF** `{{$json.tier}}` is `A` or `B`, continue; else stop (optionally log to a sheet).
4. **HTTP Request** `POST {{API}}/operators/{{$json.operator_id}}/draft`.
5. **IF** any draft has `status == "needs_fix"`: post the `errors` to Slack for manual editing.
6. **Slack: Send message** to `#outbound-review` with the operator, tier, top 3 score factors and the
   LinkedIn note text, plus a link to the dashboard draft review page. A human approves in the dashboard.
   n8n never approves or sends.

## Flow 2: Reply in sending tool -> log -> suppress or alert -> CRM

Use with Instantly / Smartlead reply webhooks (configure in the tool; check its current payload fields).

1. **Trigger: Webhook** from the sending tool on "reply received".
2. **Set** node: map the tool's payload to `{email, text, channel: "email", hook_id, list_name}`.
   `hook_id` and `list_name` are columns in our export CSV, so map them from the lead's custom variables.
3. **HTTP Request** `POST {{API}}/webhooks/reply` with that body.
4. **IF** `{{$json.suppressed}}`: stop. The address is now on the suppression list. Also pause the lead in the
   sending tool (manual step or the tool's own API node; this repo does not call it).
5. **IF** `{{$json.suggest_positive}}`: **Slack** DM to the founder/GTM owner: "Possible positive reply from
   ...". A human reads the thread and, if positive, re-calls step 3 with `positive: true` (or logs it in the
   dashboard).
6. **Optional**: `hostop crm --attio` on a schedule (Cron node -> Execute Command) to push stages to Attio,
   or import the CRM CSV.

### Notes
- Keep the API on a private network or behind n8n's credentials store; rotate the token.
- The positive-reply hint is a keyword heuristic for alerting only; it is never logged as positive by itself.
