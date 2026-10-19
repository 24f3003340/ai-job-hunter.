import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default function globalSetup() {
  const dir = path.resolve(__dirname, '../.e2e')
  mkdirSync(dir, { recursive: true })
  const py = process.env.E2E_PYTHON ?? path.resolve(__dirname, '../../backend/.venv/bin/python')
  execFileSync(py, [path.resolve(__dirname, 'make_cv.py'), path.join(dir, 'cv.pdf')])
}
