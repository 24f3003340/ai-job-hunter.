import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { profileApi } from '../api/endpoints'
import { InProgressNote, ProfileForm, toDraft } from '../components/ProfileForm'
import { Alert, ErrorAlert, Loading, PageTitle } from '../components/ui'

export function ProfilePage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['profile'], queryFn: profileApi.get })
  const save = useMutation({ mutationFn: profileApi.put, onSuccess: (p) => qc.setQueryData(['profile'], p) })
  return (
    <>
      <PageTitle>Profile</PageTitle>
      <p>This is the information generated resumes are allowed to use. <Link to="/cv">Import it from a CV</Link> or edit it here.</p>
      <InProgressNote />
      {q.isLoading && <Loading />}
      <ErrorAlert error={q.error} />
      {q.data && (
        <>
          <p className="muted">Profile version {q.data.profile_version}. Each save creates a new version; existing resume versions keep the profile snapshot they were built from.</p>
          {save.isSuccess && <Alert kind="ok">Profile saved (version {save.data.profile_version}).</Alert>}
          <ErrorAlert error={save.error} />
          <ProfileForm key={q.data.profile_version} showPreferences initial={toDraft(q.data)} busy={save.isPending}
            submitLabel="Save profile" onSubmit={(d) => save.mutate(d)} />
        </>
      )}
    </>
  )
}
