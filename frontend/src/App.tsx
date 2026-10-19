import { Navigate, Route, Routes } from 'react-router-dom'
import { PublicShell, RequireAuth } from './components/Layout'
import { ApplicationReviewPage, ApplicationsPage } from './pages/ApplicationPages'
import { ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage, VerifyEmailPage } from './pages/AuthPages'
import { CvDetailPage, CvListPage } from './pages/CvPages'
import { DashboardPage } from './pages/DashboardPage'
import { JobDetailPage, JobNewPage, JobsPage } from './pages/JobPages'
import { ProfilePage } from './pages/ProfilePage'
import { ResumePage } from './pages/ResumePage'
import { SettingsPage } from './pages/SettingsPage'

export function App() {
  return (
    <Routes>
      <Route element={<PublicShell />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/new" element={<JobNewPage />} />
        <Route path="/jobs/:id" element={<JobDetailPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/cv" element={<CvListPage />} />
        <Route path="/cv/:id" element={<CvDetailPage />} />
        <Route path="/resumes/:id" element={<ResumePage />} />
        <Route path="/applications" element={<ApplicationsPage />} />
        <Route path="/applications/:id" element={<ApplicationReviewPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
