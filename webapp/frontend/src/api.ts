// Vite serves the frontend on 5173 during development; the production nginx
// config proxies /api requests to the backend, so keep the relative URL there.
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? 'http://localhost:8000' : '')

export interface TaskStatus {
  task_id: string
  state: string | null
}

export interface RunStatus {
  dag_run_id: string
  state: string
  start_date: string | null
  end_date: string | null
  tasks: TaskStatus[]
}

export interface DataFreshness {
  duckdb_file_exists: boolean
  duckdb_last_modified: string | null
  narrative_last_generated: string | null
  narrative_last_verdict: string | null
  note: string
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const contentType = res.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) {
      const body = await res.json() as { detail?: string }
      throw new Error(body.detail ?? `Request failed (${res.status})`)
    }
    const body = await res.text()
    throw new Error(body || `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

export async function askAI(question: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  const data = await handle<{ answer: string }>(res)
  return data.answer
}

export async function triggerDag(dryRun: boolean): Promise<{ dag_run_id: string; state: string }> {
  const res = await fetch(`${API_BASE}/api/trigger?dry_run=${dryRun}`, { method: 'POST' })
  return handle(res)
}

export async function getLatestStatus(): Promise<RunStatus> {
  const res = await fetch(`${API_BASE}/api/status/latest`)
  return handle(res)
}

export async function getDataFreshness(): Promise<DataFreshness> {
  const res = await fetch(`${API_BASE}/api/data-freshness`)
  return handle(res)
}
