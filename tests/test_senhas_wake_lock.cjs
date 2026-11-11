const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/senhas-wake-lock.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function setup({ supported = true, secure = true, request } = {}) {
  const events = {};
  const elements = Object.fromEntries(['notice', 'message', 'activate'].map(name => [
    `wake-lock-${name}`, { hidden: true, addEventListener(type, fn) { this[type] = fn; } },
  ]));
  let now = 0;
  let calls = 0;
  let releases = 0;
  let last;
  const timers = new Map();
  let timerId = 0;
  const document = {
    visibilityState: 'visible',
    getElementById: id => elements[id],
    addEventListener: (type, fn) => { events[type] = fn; },
  };
  const window = {
    isSecureContext: secure,
    addEventListener: (type, fn) => { events[type] = fn; },
    setTimeout: (fn, delay) => { timers.set(++timerId, { fn, at: now + delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
  };
  const makeLock = () => {
    let onRelease;
    return {
      released: false,
      addEventListener: (_, fn) => { onRelease = fn; },
      async release() { releases++; this.released = true; onRelease?.(); },
    };
  };
  const navigator = supported ? { wakeLock: { request: type => {
    assert.equal(type, 'screen');
    calls++;
    last = makeLock();
    return request ? request(last) : Promise.resolve(last);
  } } } : {};
  vm.runInNewContext(source, { document, window, navigator, Date: { now: () => now } });
  return {
    elements, document, events, timers,
    calls: () => calls, releases: () => releases, lock: () => last,
    async tick(ms = 3000) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= now) { timers.delete(id); timer.fn(); }
      }
      await flush();
    },
    async visibility(value) { document.visibilityState = value; events.visibilitychange(); await flush(); },
  };
}

test('automatic acquisition and overlapping lifecycle events use a single request', async () => {
  let resolve;
  const state = setup({ request: lock => new Promise(done => { resolve = () => done(lock); }) });
  state.events.pageshow();
  state.events.visibilitychange();
  assert.equal(state.calls(), 1);
  resolve();
  await flush();
  assert.equal(state.elements['wake-lock-notice'].hidden, true);
});

test('hidden page releases and reacquires on return without simultaneous requests', async () => {
  const state = setup();
  await flush();
  await state.visibility('hidden');
  assert.equal(state.releases(), 1);
  assert.equal(state.timers.size, 0);
  await state.visibility('visible');
  state.events.pageshow();
  await state.tick();
  assert.equal(state.calls(), 2);
});

test('pagehide releases, pageshow restores a page from cache', async () => {
  const state = setup();
  await flush();
  state.events.pagehide();
  await flush();
  assert.equal(state.releases(), 1);
  state.events.pageshow();
  await state.tick();
  assert.equal(state.calls(), 2);
});

test('a pending request resolved after pagehide is released immediately', async () => {
  let resolve;
  const state = setup({ request: lock => new Promise(done => { resolve = () => done(lock); }) });
  state.events.pagehide();
  resolve();
  await flush();
  assert.equal(state.releases(), 1);
  assert.equal(state.timers.size, 0);
});

test('involuntary release recovery is delayed and bounded, even after successes', async () => {
  const state = setup();
  await flush();
  for (let i = 0; i < 3; i++) {
    await state.lock().release();
    if (i < 2) {
      assert.equal(state.calls(), i + 1);
      await state.tick();
    }
  }
  assert.equal(state.calls(), 3);
  assert.equal(state.timers.size, 0);
  assert.equal(state.elements['wake-lock-notice'].hidden, false);
});

test('rejection offers one trusted activation and does not poll or intercept emission', async () => {
  const state = setup({ request: () => Promise.reject(new Error('NotAllowedError')) });
  await flush();
  assert.equal(state.elements['wake-lock-activate'].hidden, false);
  assert.equal(state.timers.size, 0);
  state.elements['wake-lock-activate'].click({ isTrusted: true });
  await flush();
  state.elements['wake-lock-activate'].click({ isTrusted: true });
  assert.equal(state.calls(), 2);
  assert.equal(state.elements['wake-lock-activate'].hidden, true);
  assert.equal(state.elements['wake-lock-notice'].hidden, false);
});

test('unsupported or insecure browsers show guidance without requesting a lock', () => {
  for (const options of [{ supported: false }, { secure: false }]) {
    const state = setup(options);
    assert.equal(state.calls(), 0);
    assert.equal(state.elements['wake-lock-notice'].hidden, false);
    assert.equal(state.elements['wake-lock-activate'].hidden, true);
  }
});

test('hiding cancels a scheduled recovery', async () => {
  const state = setup();
  await flush();
  await state.lock().release();
  await state.visibility('hidden');
  await state.tick();
  assert.equal(state.calls(), 1);
  assert.equal(state.timers.size, 0);
});
