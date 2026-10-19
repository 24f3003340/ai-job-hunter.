import type { Profile } from '../api/types'

/** Resolve an evidence ref like "experience[0].bullets[1]" against a profile. Returns null if it cannot be resolved. */
export function resolveEvidence(profile: Profile, ref: string): string | null {
  const m = /^(skills|education|experience|projects|certifications)\[(\d+)\](?:\.bullets\[(\d+)\])?$/.exec(ref)
  if (!m) return ref === 'profile.full_name' ? profile.full_name : null
  const [, sec, i, j] = m
  const item = (profile as unknown as Record<string, Record<string, unknown>[]>)[sec]?.[Number(i)]
  if (!item) return null
  if (j !== undefined) { const b = (item.bullets as string[] | undefined)?.[Number(j)]; return b ?? null }
  switch (sec) {
    case 'skills': return String(item.name)
    case 'education': return [item.degree, item.institution, item.status === 'in_progress' ? '(in progress)' : '(completed)'].filter(Boolean).join(' – ')
    case 'experience': return [item.title, item.employer].filter(Boolean).join(' at ')
    case 'projects': return String(item.name)
    default: return [item.name, item.issuer].filter(Boolean).join(' – ')
  }
}
