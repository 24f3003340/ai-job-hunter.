import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import * as axeMatchers from 'vitest-axe/matchers'
import { session } from '../auth/session'
import { resetFocusBehaviourForTests } from '../components/ui'
import { server } from './server'

expect.extend(axeMatchers)
beforeAll(() => server.listen({ onUnhandledFrame: 'error' })) // any un-mocked request fails the test: no real network
afterEach(() => { cleanup(); resetFocusBehaviourForTests(); (window as unknown as { __downloads?: string[] }).__downloads = []; server.resetHandlers(); session.clear(); session.clearExpiredFlag(); window.history.replaceState({}, '', '/') })
afterAll(() => server.close())

// jsdom lacks these
if (!URL.createObjectURL) { URL.createObjectURL = () => 'blob:test'; URL.revokeObjectURL = () => undefined }
HTMLAnchorElement.prototype.click = function click() { (window as unknown as { __downloads: string[] }).__downloads = [...((window as unknown as { __downloads?: string[] }).__downloads ?? []), this.download] }
