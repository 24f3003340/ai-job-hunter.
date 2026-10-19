import js from '@eslint/js'
import globals from 'globals'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'playwright-report', 'test-results', 'node_modules'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // CV / job text must never be rendered as HTML.
      'no-restricted-syntax': ['error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: 'Never render untrusted content as HTML.' }],
      'no-restricted-globals': ['error', { name: 'localStorage', message: 'No secrets in web storage.' }],
      'no-restricted-properties': ['error',
        { object: 'window', property: 'localStorage', message: 'No secrets in web storage.' },
        { object: 'window', property: 'sessionStorage', message: 'No secrets in web storage.' }],
    },
  },
  {
    // Tests inspect web storage to prove nothing is written there.
    files: ['**/*.test.{ts,tsx}'],
    rules: { 'no-restricted-globals': 'off', 'no-restricted-properties': 'off' },
  },
)
