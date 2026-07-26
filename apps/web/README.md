# Web

The Next.js application provides the case workspace and analysis reports.

```bash
npm run dev --workspace @logan/web
```

Routes:

- `/login`
- `/cases`
- `/cases/new`
- `/cases/{case_id}`
- `/cases/{case_id}/runs/{run_id}/summary`
- `/cases/{case_id}/runs/{run_id}/temporal`
- `/cases/{case_id}/runs/{run_id}/logs`
- `/cases/{case_id}/runs/{run_id}/causal-graph`
- `/cases/{case_id}/runs/{run_id}/causal-summary`

Set `NEXT_PUBLIC_API_BASE_URL` when the API is not available at `http://localhost:8000`.
