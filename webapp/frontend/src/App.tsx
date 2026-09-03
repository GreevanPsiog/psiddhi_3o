import { useEffect, useRef, useState } from 'react'
import {
  askAI,
  triggerDag,
  getLatestStatus,
  getDataFreshness,
  type RunStatus,
  type DataFreshness,
} from './api'

function StateBadge({ state }: { state: string | null | undefined }) {
  const s = (state ?? 'unknown').toLowerCase()
  const className =
    s === 'success' ? 'badge badge-success' :
    s === 'failed' ? 'badge badge-failed' :
    s === 'running' || s === 'queued' ? 'badge badge-running' :
    'badge badge-neutral'
  return <span className={className}>{state ?? 'pending'}</span>
}

function AskPanel() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleAsk() {
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      const result = await askAI(question)
      setAnswer(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card">
      <h2>Ask about the claims data</h2>
      <p className="muted">Answers are grounded strictly in the latest analytics output.</p>
      <div className="ask-row">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
          placeholder="e.g. Which category had the highest total billed amount?"
        />
        <button onClick={handleAsk} disabled={loading || !question.trim()}>
          {loading ? 'Asking…' : 'Ask'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {answer && <p className="answer">{answer}</p>}
    </section>
  )
}

function PipelinePanel() {
  const [status, setStatus] = useState<RunStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function refreshStatus() {
    try {
      const s = await getLatestStatus()
      setStatus(s)
      setError(null)
      const finished = s.state === 'success' || s.state === 'failed'
      if (finished && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach Airflow')
    }
  }

  async function handleTrigger(dryRun: boolean) {
    setTriggering(true)
    setError(null)
    try {
      await triggerDag(dryRun)
      await refreshStatus()
      pollRef.current = setInterval(refreshStatus, 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Trigger failed')
    } finally {
      setTriggering(false)
    }
  }

  useEffect(() => {
    refreshStatus()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="card">
      <h2>Pipeline</h2>
      <div className="trigger-row">
        <button onClick={() => handleTrigger(true)} disabled={triggering}>
          Trigger (dry run)
        </button>
        <button onClick={() => handleTrigger(false)} disabled={triggering} className="primary">
          Trigger (full run)
        </button>
        <button onClick={refreshStatus} className="ghost">Refresh status</button>
      </div>
      {error && <p className="error">{error}</p>}
      {status && (
        <div className="status-block">
          <div className="status-header">
            <span>Run: {status.dag_run_id}</span>
            <StateBadge state={status.state} />
          </div>
          <ul className="task-list">
            {status.tasks.map((t) => (
              <li key={t.task_id}>
                <span>{t.task_id}</span>
                <StateBadge state={t.state} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function DataFreshnessPanel() {
  const [freshness, setFreshness] = useState<DataFreshness | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      const f = await getDataFreshness()
      setFreshness(f)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load data freshness')
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <section className="card">
      <h2>Data freshness</h2>
      {error && <p className="error">{error}</p>}
      {freshness && (
        <>
          <p>
            Analytics last computed:{' '}
            <strong>{freshness.duckdb_last_modified ?? 'never'}</strong>
          </p>
          <p>
            Last narrative generated:{' '}
            <strong>{freshness.narrative_last_generated ?? 'never'}</strong>
            {freshness.narrative_last_verdict && (
              <> — <StateBadge state={freshness.narrative_last_verdict} /></>
            )}
          </p>
          <p className="muted small">{freshness.note}</p>
        </>
      )}
      <button className="ghost" onClick={load}>Refresh</button>
    </section>
  )
}

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>Psiddhi Claims Platform</h1>
        <p className="muted">Companion app — ask questions, run the pipeline, check freshness</p>
      </header>
      <main>
        <AskPanel />
        <PipelinePanel />
        <DataFreshnessPanel />
      </main>
    </div>
  )
}
