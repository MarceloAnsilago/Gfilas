const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/painel-audio.js'), 'utf8');

function setup({ volume = 70, video = null, delayed = false } = {}) {
  let events;
  const iframe = { src: 'https://www.youtube-nocookie.com/embed/videoseries?list=test&mute=1' };
  const player = { getVolume: () => volume, setVolume: value => { volume = value; } };
  const context = {
    window: {}, URL, location: { href: 'https://example.com/painel', origin: 'https://example.com' },
    document: {
      querySelector: selector => selector.endsWith(' video') ? video : iframe,
      createElement: () => ({}), head: { appendChild() {} },
    },
    YT: { Player: function (_, options) { events = options.events; return player; } },
  };
  context.window.YT = context.YT;
  vm.runInNewContext(source, context);
  if (!delayed) events.onReady();
  return { media: context.window.painelMedia, volume: () => volume, ready: () => events.onReady(), iframe };
}

test('repeated calls preserve the original YouTube volume and mute setting', () => {
  const state = setup();
  state.media.lower();
  state.media.lower();
  assert.equal(state.volume(), 15);
  state.media.restore();
  assert.equal(state.volume(), 70);
  assert.equal(new URL(state.iframe.src).searchParams.get('mute'), '1');
});

test('quiet video is never made louder', () => {
  const state = setup({ volume: 5 });
  state.media.lower();
  assert.equal(state.volume(), 5);
  state.media.restore();
  assert.equal(state.volume(), 5);
});

test('player becoming ready during announcement lowers then restores volume', () => {
  const state = setup({ delayed: true });
  state.media.lower();
  state.ready();
  assert.equal(state.volume(), 15);
  state.media.restore();
  assert.equal(state.volume(), 70);
});

test('native video restores volume after overlapping calls', () => {
  const video = { volume: 0.8 };
  const state = setup({ video });
  state.media.lower();
  state.media.lower();
  assert.equal(video.volume, 0.15);
  state.media.restore();
  assert.equal(video.volume, 0.8);
});
