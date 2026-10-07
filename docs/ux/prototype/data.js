/* Demo data for the P-UX3 prototype. Nothing here is read from or written to a backend. */

const LANGS = { en: 'English', ru: 'Русский' };
const FORMATS = { '9:16': '9:16 Portrait', '16:9': '16:9 Landscape' };
const MODES = { generated: 'Generated voice', uploaded: 'Uploaded voice' };
const CAPTIONS = { standard: 'On — Standard', punch: 'On — Punch', none: 'Off' };
const PACES = { slow: 'Slow — ~145 wpm', normal: 'Normal — ~160 wpm', fast: 'Fast — ~172 wpm' };
const STYLES = { educational: 'Educational', emotional: 'Emotional' };
const VOICES = { Kore: 'Kore', Charon: 'Charon', Aoede: 'Aoede', Puck: 'Puck' };

// One pipeline for every run. Where the script comes from is chosen in the Script step.
const STEPS = ['script', 'voice', 'storyboard', 'video', 'metadata'];
const SOURCES = { generate: 'Generate from a brief', paste: 'Paste a script', upload: 'Take it from a voiceover' };
const STEP_LABELS = {
  script: 'Script', voice: 'Voice',
  storyboard: 'Storyboard', video: 'Video', metadata: 'Metadata',
};

const DB = {
  // Tenant defaults: what every project inherits unless it overrides.
  defaults: { language: 'en', format: '9:16', captions: 'standard', voice: 'Kore', spendCap: 2.0 },

  integrations: [
    { id: 'claude', name: 'Anthropic Claude', use: 'Script, storyboard, metadata', key: 'env', model: 'claude-sonnet-5-5', models: ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-4-5'] },
    { id: 'gemini', name: 'Google Gemini TTS', use: 'Generated voice', key: 'env', model: 'gemini-2.5-flash-tts', models: ['gemini-2.5-flash-tts'] },
    { id: 'deepgram', name: 'Deepgram', use: 'Transcribing uploaded voiceovers', key: 'env', model: 'nova-2', models: ['nova-2', 'nova-3'] },
    { id: 'openai', name: 'OpenAI Images', use: 'AI images per scene', key: 'tenant', hint: '4f2a', model: 'gpt-image-1', models: ['gpt-image-1'], provider: true, active: true },
    { id: 'kie', name: 'kie.ai', use: 'AI images per scene', key: 'none', model: '', models: ['nano-banana'], provider: true },
    { id: 'pexels', name: 'Pexels', use: 'Stock footage and images', key: 'env' },
    { id: 'pixabay', name: 'Pixabay', use: 'Stock footage and images', key: 'env', warn: 'Rotate this key — the old one appeared in DEV logs.' },
    { id: 'freesound', name: 'Freesound', use: 'Sound effects', key: 'env' },
    { id: 'n8n', name: 'n8n', use: 'Publishing to channels', key: 'none', planned: 'P16' },
  ],

  projects: [
    { id: 'the', name: 'The Housing Equation', niche: 'american housing economics', source: 'generate',
      settings: { language: 'en', format: '9:16' }, aiLook: 'Muted editorial illustration, flat colours, soft grain, no text', updated: '2026-10-07' },
    { id: 'dom', name: 'Дом и деньги', niche: 'рынок жилья простыми словами', source: 'upload',
      settings: { language: 'ru', captions: 'punch' }, aiLook: '', updated: '2026-10-06' },
    { id: 'lab', name: 'Format lab', niche: '', source: 'generate', settings: {}, aiLook: '', updated: '2026-09-28' },
  ],

  ideas: [
    { id: 'i1', project: 'the', title: 'Why starter homes disappeared from America', summary: 'In 1982, 40% of new construction was entry-level. By 2020 it was 7%. Zoning and fixed permit fees did it.', method: 'manual', source: 'NAHB report', date: '2026-10-01' },
    { id: 'i2', project: 'the', title: 'The 3% mortgage lock-in, explained in 60 seconds', summary: 'Owners with pandemic-era rates will not sell. What that does to supply.', method: 'manual', source: '', date: '2026-10-03' },
    { id: 'i3', project: 'the', title: 'What a $40,000 permit fee does to a $200k house', summary: 'The same fee on a starter home and a luxury build — the maths.', method: 'trend', source: 'Google Trends · 7 days', date: '2026-10-05' },
    { id: 'i4', project: 'the', title: 'Institutional buyers: how much do they really own?', summary: '', method: 'competitor', source: 'Outlier · 4.2× channel average', date: '2026-10-06' },
    { id: 'i5', project: 'dom', title: 'Почему аренда дорожает быстрее зарплат', summary: 'Три причины на цифрах.', method: 'manual', source: '', date: '2026-10-04' },
  ],

  runs: [
    { id: 'r-8f31c2', project: 'the', title: 'Why starter homes disappeared from America', ideas: ['i1'], mode: 'generated', language: 'en', format: '9:16',
      captions: 'standard', pace: 'normal', style: 'educational', music: 'Slow ember', done: 5, status: 'complete', cost: 0.42, created: '2026-10-02', acquired: true, rendered: 'server' },
    { id: 'r-27ab90', project: 'the', title: 'The 3% mortgage lock-in, explained in 60 seconds', ideas: ['i2'], mode: 'uploaded', language: 'en', format: '9:16',
      captions: 'punch', pace: 'normal', style: 'educational', music: 'Low tide', done: 2, status: 'running', cost: 0.06, created: '2026-10-06', acquired: false },
    { id: 'r-c04e7d', project: 'the', title: 'Rent vs buy in 2026 — a quick take', ideas: [], mode: 'generated', language: 'en', format: '16:9',
      captions: 'standard', pace: 'fast', style: 'educational', music: '', done: 1, status: 'failed', cost: 0.03, created: '2026-10-07', acquired: false, error: 'Voice generation failed: the TTS provider timed out. Retry the step.' },
    { id: 'r-5d1e88', project: 'dom', title: 'Почему аренда дорожает быстрее зарплат', ideas: ['i5'], mode: 'uploaded', language: 'ru', format: '9:16',
      captions: 'punch', pace: 'normal', style: 'educational', music: 'Low tide', done: 5, status: 'complete', cost: 0.11, created: '2026-10-05', acquired: true, rendered: 'capcut' },
  ],

  script: "In 1980, the average first home in America cost three times the median income. Today it costs seven. But this isn't just inflation — starter homes have physically vanished. In 1982, 40% of new construction was entry-level housing. By 2020, it was 7%. Builders didn't abandon small homes by accident. Zoning laws set minimum lot sizes. Permit fees became fixed costs that only pencil out on luxury builds. So the starter home didn't die of natural causes. It was regulated out of existence — one city council vote at a time.",

  scenes: [
    { n: 1, dur: 6, vo: 'In 1980, the average first home in America cost three times the median income. Today it costs seven.', strategy: 'stock', query: 'suburban street 1980s', hue: 210, text: '3× → 7× income', sfx: '' },
    { n: 2, dur: 6, vo: "But this isn't just inflation — starter homes have physically vanished.", strategy: 'stock', query: 'empty lot for sale sign', hue: 30, text: '', sfx: 'Whoosh — soft' },
    { n: 3, dur: 7, vo: 'In 1982, 40% of new construction was entry-level housing. By 2020, it was 7%.', strategy: 'ai', prompt: 'Bar chart made of small houses shrinking from left to right', hue: 265, text: '40% → 7%', sfx: '' },
    { n: 4, dur: 7, vo: "Builders didn't abandon small homes by accident. Zoning laws set minimum lot sizes.", strategy: 'stock', query: 'city council zoning map', hue: 150, text: '', sfx: '' },
    { n: 5, dur: 7, vo: 'Permit fees became fixed costs that only pencil out on luxury builds.', strategy: 'upload', hue: 0, text: '$40,000 in fees', sfx: 'Cash register' },
    { n: 6, dur: 8, vo: 'It was regulated out of existence — one city council vote at a time.', strategy: 'stock', query: 'gavel council vote', hue: 340, text: '', sfx: '' },
  ],

  // Libraries — every asset names its project and run and has an ID.
  assets: {
    videos: [
      { id: 'VID-0041', name: 'starter-homes_9x16.mp4', project: 'the', run: 'r-8f31c2', facts: '0:41 · 1080×1920 · server render', date: '2026-10-02', hue: 210 },
      { id: 'VID-0040', name: 'starter-homes_capcut.mp4', project: 'the', run: 'r-8f31c2', facts: '0:43 · 1080×1920 · uploaded from CapCut', date: '2026-10-02', hue: 225 },
      { id: 'VID-0044', name: 'arenda-vs-zarplaty.mp4', project: 'dom', run: 'r-5d1e88', facts: '0:52 · 1080×1920 · uploaded from CapCut', date: '2026-10-05', hue: 20 },
    ],
    audio: [
      { id: 'AUD-0102', name: 'voiceover.wav', project: 'the', run: 'r-8f31c2', facts: '0:41 · generated · Kore', date: '2026-10-02', facet: 'generated' },
      { id: 'AUD-0107', name: 'uploaded.m4a', project: 'the', run: 'r-27ab90', facts: '0:58 · uploaded · English', date: '2026-10-06', facet: 'uploaded' },
      { id: 'AUD-0105', name: 'uploaded.mp3', project: 'dom', run: 'r-5d1e88', facts: '0:52 · uploaded · Русский', date: '2026-10-05', facet: 'uploaded' },
    ],
    footage: [
      { id: 'FTG-0311', name: 'scene_01.mp4', project: 'the', run: 'r-8f31c2', facts: 'video · Pexels · "suburban street 1980s"', date: '2026-10-02', hue: 210, facet: 'pexels' },
      { id: 'FTG-0312', name: 'scene_02.mp4', project: 'the', run: 'r-8f31c2', facts: 'video · Pixabay · "empty lot for sale sign"', date: '2026-10-02', hue: 30, facet: 'pixabay' },
      { id: 'FTG-0314', name: 'scene_04.jpg', project: 'the', run: 'r-8f31c2', facts: 'image · Pexels · "city council zoning map"', date: '2026-10-02', hue: 150, facet: 'pexels' },
      { id: 'FTG-0315', name: 'scene_05.mp4', project: 'the', run: 'r-8f31c2', facts: 'video · uploaded by operator', date: '2026-10-02', hue: 0, facet: 'upload' },
      { id: 'FTG-0316', name: 'scene_06.mp4', project: 'the', run: 'r-8f31c2', facts: 'video · Pexels · "gavel council vote"', date: '2026-10-02', hue: 340, facet: 'pexels' },
      { id: 'FTG-0330', name: 'scene_01.mp4', project: 'dom', run: 'r-5d1e88', facts: 'video · Pixabay · "apartment block evening"', date: '2026-10-05', hue: 190, facet: 'pixabay' },
      { id: 'FTG-0331', name: 'scene_03.jpg', project: 'dom', run: 'r-5d1e88', facts: 'image · Pexels · "rental contract keys"', date: '2026-10-05', hue: 60, facet: 'pexels' },
    ],
    ai: [
      { id: 'AIG-0057', name: 'scene_03_ai_a91c.png', project: 'the', run: 'r-8f31c2', facts: 'OpenAI · $0.04 · in use · "Bar chart made of small houses…"', date: '2026-10-02', hue: 265, facet: 'in use' },
      { id: 'AIG-0056', name: 'scene_03_ai_77e0.png', project: 'the', run: 'r-8f31c2', facts: 'OpenAI · $0.04 · replaced · "Row of houses fading out…"', date: '2026-10-02', hue: 285, facet: 'replaced' },
      { id: 'AIG-0061', name: 'scene_02_ai_c3d4.png', project: 'dom', run: 'r-5d1e88', facts: 'OpenAI · $0.04 · in use · "Ruble coins stacked like a staircase…"', date: '2026-10-05', hue: 45, facet: 'in use' },
    ],
    music: [
      { id: 'MUS-0003', name: 'Slow ember', project: null, run: null, facts: 'music · 2:10 · used in 1 run', date: '2026-08-14', facet: 'music' },
      { id: 'MUS-0007', name: 'Low tide', project: null, run: null, facts: 'music · 1:48 · used in 2 runs', date: '2026-08-14', facet: 'music' },
      { id: 'SFX-0012', name: 'Whoosh — soft', project: null, run: null, facts: 'sfx · 0:01', date: '2026-09-02', facet: 'sfx' },
      { id: 'SFX-0019', name: 'Cash register', project: null, run: null, facts: 'sfx · 0:02', date: '2026-09-02', facet: 'sfx' },
    ],
  },
};

const LIBS = {
  videos: { label: 'Videos', blurb: 'Every final video in the tenant — server renders and uploads from CapCut.', thumb: true },
  audio: { label: 'Audio', blurb: 'Every voiceover, generated or uploaded.', thumb: false },
  footage: { label: 'Footage', blurb: 'Every image and clip acquired for a scene or uploaded by you.', thumb: true },
  ai: { label: 'AI generations', blurb: 'Every AI-generated image, including the ones you replaced.', thumb: true },
  music: { label: 'Music & SFX', blurb: 'Shared tracks and sounds. Runs pick from here instead of uploading each time.', thumb: false },
};
