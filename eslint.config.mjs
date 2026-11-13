import globals from 'globals';

export default [{
  files: ['src/vantage/web/*.js'],
  languageOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    globals: { ...globals.browser, ...globals.worker },
  },
  rules: { 'no-undef': 'error' },
}];
