import react from 'eslint-plugin-react'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
    ],
  },
  {
    files: ['**/*.{js,jsx}'],
    plugins: {
      react,
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    rules: {
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'react/jsx-uses-vars': 'error',
    },
  },
]