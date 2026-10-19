import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const API = 'http://api.test/api/v1'
export const ME = { id: 'u1', email: 'riya@example.com', email_verified: true, ai_consent: false }

export const server = setupServer(
  http.get(`${API}/auth/me`, () => HttpResponse.json(ME)),
)
export { http, HttpResponse }
