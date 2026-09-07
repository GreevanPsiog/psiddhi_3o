const API_BASE = 'http://localhost:8000'

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
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed (${res.status})`)
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
