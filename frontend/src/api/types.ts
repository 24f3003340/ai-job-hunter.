// Mirrors the FastAPI schemas (backend/app/schemas.py, routers/*). Hand-written; see docs/FRONTEND.md.
export interface Me { id: string; email: string; email_verified: boolean; ai_consent: boolean }

export type EduStatus = 'completed' | 'in_progress'
export interface Skill { name: string; level?: 'beginner' | 'intermediate' | 'advanced' | null; verified: boolean }
export interface Education {
  degree: string; institution: string; status: EduStatus
  start_date?: string | null; end_date?: string | null; verified: boolean
}
export interface Experience {
  title: string; employer: string; start_date?: string | null; end_date?: string | null; current: boolean
  description: string; bullets: string[]
}
export interface Project { name: string; description: string; bullets: string[]; technologies: string[]; url?: string | null }
export interface Certification { name: string; issuer: string; date?: string | null }
export interface Preferences {
  target_titles: string[]; min_salary_monthly: number | null; cities: string[]; remote_ok: boolean
  relocation_ok: boolean; experience_years: number | null; excluded_employers: string[]; excluded_locations: string[]
}
export interface ProfileData {
  full_name: string; phone: string; education: Education[]; experience: Experience[]; projects: Project[]
  skills: Skill[]; certifications: Certification[]; preferences: Preferences
}
export interface Profile extends ProfileData { profile_version: number }

export interface Job {
  id: string; title: string; company: string; location: string; remote: boolean | null; description: string
  salary_min: number | null; salary_max: number | null; salary_period: 'month' | 'year' | null
  experience_min: number | null; application_url: string | null; status: string; source: string
  first_seen_at: string; last_verified_at: string | null; closing_date: string | null
}
export interface JobInput {
  title: string; company: string; location?: string; remote?: boolean | null; description?: string
  required_skills?: string[]; preferred_skills?: string[]; salary_min?: number | null; salary_max?: number | null
  salary_period?: 'month' | 'year' | null; experience_min?: number | null; requires_degree_completed?: boolean | null
  application_url?: string | null
}
export interface MatchReport {
  score: number | null; components: Record<string, number | null>; unknown_dimensions: string[]; known_weight: number
  matched_skills: string[]; missing_skills: string[]; hard_constraints: string[]; eligibility_warnings: string[]
  salary_confidence: string; freshness: string; disqualified: boolean; explanation: string
}

export interface DocumentMeta {
  id: string; document_type: string; filename: string; mime_type: string; size_bytes: number; checksum: string
  scan_status: 'clean' | 'not_configured' | 'error' | string; parsing_status: string; created_at: string
}
export interface Flag { id: string; code: string; path: string; severity: 'info' | 'warning'; message: string }
export interface ParsedEducation {
  degree: string; institution: string; start_date: string | null; end_date: string | null
  status: EduStatus | null; suggested_status: EduStatus | null; confidence: string
}
export interface ParsedCv {
  full_name: string; email: string | null; phone: string; education: ParsedEducation[]
  experience: (Experience & { confidence?: string })[]; projects: (Project & { confidence?: string })[]
  skills: Skill[]; certifications: Certification[]
}
export interface ParsePreview {
  parse_id: string; document_id: string; status: string; parser_version: string; parsed: ParsedCv; flags: Flag[]; notice: string
}

export interface ClaimReason { code: string; message: string }
export interface Claim {
  id: string; section: string; text: string; evidence: string[]; status: 'supported' | 'needs_review'
  reasons: ClaimReason[]; decision?: 'accept' | 'reject' | null
}
export type ReviewStatus = 'clean' | 'reviewed' | 'needs_review' | 'rejected'
export interface ResumeSummary {
  id: string; job_id: string; version_number: number; parent_version_id: string | null; source_profile_version: number
  generation_source: string; provider: string | null; review_status: ReviewStatus; created_at: string; content_hash: string | null
}
export interface ResumeContent {
  template: string; header: { name: string; email: string; phone: string }
  summary: { id: string; text: string } | null
  skills: { name: string }[]
  experience: { ref: string; title: string; employer: string; start_date: string | null; end_date: string | null; current: boolean; bullets: { id: string; text: string }[] }[]
  projects: { ref: string; name: string; technologies: string[]; url: string | null; bullets: { id: string; text: string }[] }[]
  education: { ref: string; degree: string; institution: string; status: EduStatus; start_date: string | null; end_date: string | null }[]
  certifications: { ref: string; name: string; issuer: string; date: string | null }[]
}
export interface ResumeWarning { code: string; severity: string; message: string }
export interface ResumeDetail extends ResumeSummary {
  content: ResumeContent; claims: Claim[]; warnings: ResumeWarning[]; change_summary: string[]
  unresolved_claims: string[]; rejected_claims: string[]
}

export interface AnswerInput { question: string; answer: string; source_of_truth?: 'user' | 'profile' | 'ai_draft'; user_confirmed: boolean }
export interface Application {
  id: string; job_id: string; status: string; submitted_at: string | null; submission_method: string | null
  confirmation_reference: string | null; resume_version_id: string | null; cover_letter_id: string | null
  answers: AnswerInput[]; blockers: string[]; manual_application_url: string | null; notes: string
}
export interface ApplicationDetail extends Application {
  history: { from: string | null; to: string; type: string; at: string }[]
}
export interface SubmitResult extends Application { submission?: string; detail?: string }
export interface ApproveResult extends Application { package_hash: string }
