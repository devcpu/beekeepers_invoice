module.exports = [
    {
        languageOptions: {
            ecmaVersion: 2021,
            sourceType: 'script',
            globals: {
                // Browser globals
                window: 'readonly',
                document: 'readonly',
                console: 'readonly',
                alert: 'readonly',
                // jQuery
                $: 'readonly',
                jQuery: 'readonly',
                // Bootstrap
                bootstrap: 'readonly'
            }
        },
        rules: {
            'indent': ['error', 4],
            'linebreak-style': ['error', 'unix'],
            'quotes': ['error', 'single', { 'avoidEscape': true }],
            'semi': ['error', 'always'],
            'max-len': ['warn', { 'code': 160, 'ignoreUrls': true, 'ignoreStrings': true }],
            'no-unused-vars': ['warn', { 'argsIgnorePattern': '^_' }],
            'no-console': 'warn',
            'no-var': 'error',
            'prefer-const': 'warn',
            'prefer-arrow-callback': 'warn',
            'arrow-spacing': 'error',
            'no-multiple-empty-lines': ['error', { 'max': 2 }],
            'eqeqeq': ['error', 'always'],
            'curly': ['error', 'all'],
            'brace-style': ['error', '1tbs'],
            'comma-dangle': ['error', 'never'],
            'space-before-function-paren': ['error', {
                'anonymous': 'always',
                'named': 'never',
                'asyncArrow': 'always'
            }]
        }
    },
    {
        files: ['static/**/*.js'],
        languageOptions: {
            sourceType: 'script'
        }
    },
    {
        files: ['static/service-worker.js'],
        rules: {
            'no-console': 'off',
            'no-unused-vars': 'off'
        }
    },
    {
        ignores: [
            'node_modules/**',
            'venv/**',
            'pdfs/**',
            'uploads/**',
            'logs/**',
            'migrations/**',
            '.venv/**'
        ]
    }
];
