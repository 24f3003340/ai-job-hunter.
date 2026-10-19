import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { applicationsApi, jobsApi, profileApi } from '../api/endpoints'
import { Alert, ErrorAlert, Loading, PageTitle } from '../components/ui'

export function DashboardPage() {
  const jobs = useQuery({ queryKey: ['jobs', 'all'], queryFn: () => jobsApi.list({ limit: 200 }) })
  const apps = useQuery({ queryKey: ['applications'], queryFn: () => applicationsApi.list() })
  const profile = useQuery({ queryKey: ['profile'], queryFn: profileApi.get })
  const count = (xs: string[]) => apps.data?.filter((a) => xs.includes(a.status)).length ?? 0
  const loading = jobs.isLoading || apps.isLoading
  const needsProfile = profile.data && !profile.data.full_name
  const cards: [string, number, string][] = apps.data ? [
    ['Needs your review', count(['discovered', 'match_evaluated', 'ready_for_review']), '/applications'],
    ['Approved – not yet applied', count(['approved']), '/applications'],
    ['Applied (reported by you)', count(['submitted']), '/applications'],
    ['Interview / offer', count(['interview', 'offer_received']), '/applications'],
    ['Rejected / withdrawn / closed', count(['rejected', 'withdrawn', 'closed']), '/applications'],
  ] : []
  return (
    <>
      <PageTitle>Dashboard</PageTitle>
      {needsProfile && <Alert kind="info">Start by importing your CV or filling in your profile so resumes can be tailored. <Link to="/cv">Upload CV</Link> · <Link to="/profile">Edit profile</Link></Alert>}
      {loading && <Loading />}
      <ErrorAlert error={jobs.error ?? apps.error} />
      {jobs.data && (
        <div className="grid" aria-label="Job counts">
          <div className="card"><div className="stat">{jobs.data.length}</div><div>Jobs saved{jobs.data.length === 200 ? ' (showing first 200)' : ''}</div><Link to="/jobs">View jobs</Link></div>
          <div className="card"><div className="stat">{jobs.data.filter((j) => j.status === 'needs_verification').length}</div><div>Not yet verified</div></div>
          <div className="card"><div className="stat">{jobs.data.filter((j) => j.status === 'active').length}</div><div>Verified active</div></div>
        </div>
      )}
      {apps.data && (
        <>
          <h2>Applications</h2>
          {apps.data.length === 0 ? <p className="muted">No applications yet. <Link to="/jobs">Pick a job</Link> to start a draft.</p> : (
            <div className="grid">{cards.map(([label, n, to]) => <div className="card" key={label}><div className="stat">{n}</div><div>{label}</div><Link to={to}>Open tracker</Link></div>)}</div>
          )}
        </>
      )}
    </>
  )
}
