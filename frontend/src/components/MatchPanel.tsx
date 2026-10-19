import type { MatchReport } from '../api/types'
import { COMPONENT_LABEL } from '../lib/labels'
import { Alert, Badge } from './ui'

/** Shows score AND the things a score can hide: disqualifiers first, unknowns marked as unknown (never as a match). */
export function MatchPanel({ m }: { m: MatchReport }) {
  return (
    <section aria-labelledby="match-h" className="card">
      <h2 id="match-h" style={{ marginTop: 0 }}>Match explanation</h2>
      {m.hard_constraints.length > 0 && (
        <Alert kind="error" role="alert">
          <strong>Disqualifying requirements.</strong> These apply no matter how high the score is:
          <ul>{m.hard_constraints.map((c) => <li key={c}>{c}</li>)}</ul>
        </Alert>
      )}
      <p>
        <span className="stat">{m.score === null ? 'n/a' : `${m.score}`}</span>
        <span className="muted"> / 100 · based on {Math.round(m.known_weight * 100)}% of the scoring weight</span>
      </p>
      <p>{m.explanation}</p>
      <h3>Components</h3>
      <ul className="clean">
        {Object.entries(m.components).map(([k, v]) => (
          <li key={k}>
            <div className="row"><span style={{ minWidth: 130 }}>{COMPONENT_LABEL[k] ?? k}</span>
              {v === null
                ? <Badge kind="warn">Unknown – not assumed to match</Badge>
                : <><div className="bar" style={{ flex: 1, minWidth: 80 }} role="img" aria-label={`${COMPONENT_LABEL[k] ?? k}: ${v} out of 100`}><span style={{ width: `${v}%` }} /></div><span>{v}</span></>}
            </div>
          </li>
        ))}
      </ul>
      <div className="grid">
        <div><h3>Matched skills</h3>{m.matched_skills.length ? <ul>{m.matched_skills.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="muted">None</p>}</div>
        <div><h3>Missing skills</h3>{m.missing_skills.length ? <ul>{m.missing_skills.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="muted">None</p>}</div>
      </div>
      {m.eligibility_warnings.length > 0 && (<><h3>Concerns</h3><ul>{m.eligibility_warnings.map((w) => <li key={w}>{w}</li>)}</ul></>)}
      <p className="muted">Salary information: {m.salary_confidence === 'stated' ? 'stated in the listing' : 'not stated'} · Listing: {m.freshness.replace(/_/g, ' ')}</p>
    </section>
  )
}
