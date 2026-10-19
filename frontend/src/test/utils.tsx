import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../App'
import { AuthProvider } from '../auth/AuthContext'
import { session } from '../auth/session'

export function renderApp(route = '/', opts: { token?: string | null; staleTime?: number } = { token: 'test-token' }) {
  if (opts.token !== null) session.set(opts.token ?? 'test-token')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: opts.staleTime ?? 0 } } })
  const user = userEvent.setup()
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { user, qc, ...utils }
}

export const downloads = () => ((window as unknown as { __downloads?: string[] }).__downloads ?? [])
export const clearDownloads = () => { (window as unknown as { __downloads?: string[] }).__downloads = [] }

// ---- fixtures --------------------------------------------------------------------------------
export const profileFx = {
  full_name: 'Riya Sharma', phone: '', profile_version: 3,
  education: [{ degree: 'B.Tech in Computer Science', institution: 'Example Institute', status: 'in_progress', start_date: '2022', end_date: '2027', verified: true }],
  experience: [{ title: 'ML Intern', employer: 'Acme Labs', start_date: '2024-06', end_date: '2024-08', current: false, description: '', bullets: ['Built a RAG prototype over 500 documents using LangChain'] }],
  projects: [], skills: [{ name: 'Python', level: null, verified: true }], certifications: [],
  preferences: { target_titles: [], min_salary_monthly: null, cities: [], remote_ok: true, relocation_ok: false, experience_years: null, excluded_employers: [], excluded_locations: [] },
}
export const jobFx = {
  id: 'j1', title: 'NLP Engineer', company: 'Acme', location: 'Jaipur', remote: null, description: 'Build RAG systems.',
  salary_min: null, salary_max: null, salary_period: null, experience_min: null, application_url: 'https://acme.example/apply',
  status: 'active', source: 'manual', first_seen_at: '2026-01-01T00:00:00Z', last_verified_at: '2026-01-02T00:00:00Z', closing_date: null,
}
export const matchFx = {
  score: 62.5, components: { skills: 80, experience: null, role: 70, salary: null, location: 100, education: 0 },
  unknown_dimensions: ['experience', 'salary'], known_weight: 0.65, matched_skills: ['Python'], missing_skills: ['Kubernetes'],
  hard_constraints: ['Job requires a completed degree; none is recorded as completed in your profile'],
  eligibility_warnings: ['Missing required skills: Kubernetes'], salary_confidence: 'unknown', freshness: 'active', disqualified: true,
  explanation: 'Score 62.5 based on 65% of the scoring weight.',
}
export const appFx = {
  id: 'a1', job_id: 'j1', status: 'ready_for_review', submitted_at: null, submission_method: null, confirmation_reference: null,
  resume_version_id: 'r1', cover_letter_id: null,
  answers: [{ question: 'Why us?', answer: 'I like NLP', source_of_truth: 'user', user_confirmed: true }],
  blockers: [], manual_application_url: 'https://acme.example/apply', notes: '', history: [],
}
export const resumeFx = {
  id: 'r1', job_id: 'j1', version_number: 2, parent_version_id: null, source_profile_version: 3, generation_source: 'generated',
  provider: 'rule_based', review_status: 'needs_review', created_at: '2026-02-01T00:00:00Z', content_hash: 'h',
  content: {
    template: 'classic', header: { name: 'Riya Sharma', email: 'riya@example.com', phone: '' }, summary: { id: 'c1', text: 'Award-winning engineer' },
    skills: [{ name: 'Python' }],
    experience: [{ ref: 'experience[0]', title: 'ML Intern', employer: 'Acme Labs', start_date: '2024-06', end_date: '2024-08', current: false,
      bullets: [{ id: 'c2', text: 'Built a RAG prototype over 500 documents using LangChain' }] }],
    projects: [], education: [{ ref: 'education[0]', degree: 'B.Tech in Computer Science', institution: 'Example Institute', status: 'in_progress', start_date: '2022', end_date: '2027' }],
    certifications: [],
  },
  claims: [
    { id: 'c1', section: 'summary', text: 'Award-winning engineer', evidence: [], status: 'needs_review', reasons: [{ code: 'no_evidence', message: 'No supporting profile evidence is cited for this statement.' }], decision: null },
    { id: 'c2', section: 'experience[0]', text: 'Built a RAG prototype over 500 documents using LangChain', evidence: ['experience[0].bullets[0]'], status: 'supported', reasons: [], decision: null },
  ],
  warnings: [{ code: 'education_in_progress', severity: 'info', message: '“B.Tech in Computer Science” is shown as in progress; it was not changed.' }],
  change_summary: ['Skills reordered to put job-relevant skills first: Python'], unresolved_claims: ['c1'], rejected_claims: [],
}
