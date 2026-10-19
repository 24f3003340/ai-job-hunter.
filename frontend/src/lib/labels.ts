import type { ReviewStatus } from '../api/types'

/** Honest wording for application statuses. "submitted" is only ever user-reported in this product. */
export function applicationStatusLabel(status: string, method?: string | null): string {
  switch (status) {
    case 'discovered': return 'Draft'
    case 'match_evaluated': return 'Draft (match checked)'
    case 'ready_for_review': return 'Needs your review'
    case 'approved': return 'Approved by you – not yet applied'
    case 'submission_in_progress': return 'Submission in progress'
    // Never plain "Submitted": today the only way to reach this state is the user telling us they applied.
    case 'submitted': return method === 'manual_user_reported' ? 'Applied (reported by you)' : method ? `Submitted (${method.replace(/_/g, ' ')})` : 'Applied'
    case 'submission_failed': return 'Submission failed'
    case 'interview': return 'Interview'
    case 'rejected': return 'Rejected'
    case 'withdrawn': return 'Withdrawn'
    case 'offer_received': return 'Offer received'
    case 'closed': return 'Closed'
    default: return status.replace(/_/g, ' ')
  }
}

export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  clean: 'All statements consistent with your profile',
  reviewed: 'Flagged statements accepted by you',
  needs_review: 'Statements need your review',
  rejected: 'Contains a statement you rejected',
}

export const JOB_STATUS_LABEL: Record<string, string> = {
  active: 'Verified active',
  needs_verification: 'Not yet verified',
  stale: 'Possibly stale',
  expired: 'Expired',
}

export const COMPONENT_LABEL: Record<string, string> = {
  skills: 'Skills', experience: 'Experience', role: 'Role relevance', salary: 'Salary', location: 'Location', education: 'Education',
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
