// Run with: node --test scripts/test_password_reset_prefill.cjs
// Execute the actual inline script without adding a browser dependency to CI.
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const html = readFileSync(
    join(__dirname, '../templates/forget_password.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function load(fragment) {
    const events = [];
    const fields = Object.fromEntries(['username', 'token', 'new_password']
        .map(id => [id, {value: '', focus() { events.push('focus'); }}]));
    let ready;
    const location = {
        hash: fragment, pathname: '/forgetpw/', search: '',
    };
    const context = {
        window: {location}, location, URLSearchParams,
        history: {
            replaceState(state, title, url) {
                assert.equal(state, null);
                assert.equal(url, '/forgetpw/');
                location.hash = '';
                events.push('clear');
            },
        },
        document: {
            addEventListener(name, callback, options) {
                assert.equal(name, 'DOMContentLoaded');
                assert.equal(options.once, true);
                assert.equal(location.hash, '');
                events.push('listen');
                ready = callback;
            },
            getElementById(id) { return fields[id]; },
        },
    };
    // No storage, fetch, form.submit or HTML setters are exposed. Using any
    // of them would fail these tests instead of silently accepting a leak.
    vm.runInNewContext(script, context);
    const beforeReady = {...fields.token};
    if (ready) ready();
    return {fields, events, location, beforeReady};
}

test('clears fragment before DOM readiness and preserves leading zeros', () => {
    const result = load('#username=reset%2Btest%26account&token=000042');
    assert.deepEqual(result.events, ['clear', 'listen', 'focus']);
    assert.equal(result.beforeReady.value, '');
    assert.equal(result.fields.username.value, 'reset+test&account');
    assert.equal(result.fields.token.value, '000042');
    assert.equal(result.location.hash, '');
});

test('no fragment leaves manual entry untouched', () => {
    const result = load('');
    assert.deepEqual(result.events, []);
    assert.equal(result.fields.token.value, '');
});

for (const fragment of [
    '#username=test', '#token=000042', '#username=&token=000042',
    '#username=test&token=12345', '#username=test&token=1234567',
    '#username=test&token=abcdef', '#username=test&token=１２３４５６',
    '#username=test&token=000042&token=000043',
    '#username=test&username=other&token=000042',
    '#username=%20test&token=000042', '#username=test%0A&token=000042',
    `#username=${'a'.repeat(151)}&token=000042`,
    '#username=test&token=%ZZ',
]) {
    test(`invalid fragment falls back to manual entry (${fragment})`, () => {
        const result = load(fragment);
        assert.deepEqual(result.events, ['clear']);
        assert.equal(result.location.hash, '');
        assert.equal(result.fields.username.value, '');
        assert.equal(result.fields.token.value, '');
    });
}

test('HTML-like account text is assigned as a value, never interpreted', () => {
    const username = '<img src=x onerror=alert(1)>';
    const result = load(`#username=${encodeURIComponent(username)}&token=000042`);
    assert.equal(result.fields.username.value, username);
    assert.equal(result.fields.token.value, '000042');
});
