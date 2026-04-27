/**
 * gmgn_bridge/index.js — PONYIN GMGN Bridge v1.1
 * Fix: ganti 'got' dengan 'axios' (CommonJS, tanpa ESM ribet)
 */

const express = require('express');
const axios   = require('axios');

const app  = express();
const PORT = process.env.PORT || 3000;

// ── Rotate user agents ───────────────────────────────────────────────
const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
];

function randomUA() {
  return USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
}

function gmgnHeaders() {
  return {
    'accept':             'application/json, text/plain, */*',
    'accept-language':    'en-US,en;q=0.9',
    'dnt':                '1',
    'priority':           'u=1, i',
    'referer':            'https://gmgn.ai/?chain=sol',
    'sec-ch-ua':          '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile':   '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest':     'empty',
    'sec-fetch-mode':     'cors',
    'sec-fetch-site':     'same-origin',
    'user-agent':         randomUA(),
    ...(process.env.GMGN_API_KEY ? { 'x-route-key': process.env.GMGN_API_KEY } : {}),
  };
}

// ── Request helper dengan retry ──────────────────────────────────────
async function gmgnGet(url, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await axios.get(url, {
        headers: gmgnHeaders(),
        timeout: 12_000,
        maxRedirects: 5,
        validateStatus: status => status === 200,
      });
      return response.data;
    } catch (err) {
      const status = err.response?.status;
      if (status === 429) {
        const wait = (attempt + 1) * 2000;
        console.warn(`GMGN rate limit, wait ${wait}ms (attempt ${attempt + 1})`);
        await new Promise(r => setTimeout(r, wait));
      } else if (attempt < retries) {
        await new Promise(r => setTimeout(r, 500));
      } else {
        throw err;
      }
    }
  }
}

// ── Routes ───────────────────────────────────────────────────────────

app.get('/health', (req, res) => {
  res.json({ status: 'ok', ts: Date.now(), version: '1.1' });
});

/**
 * GET /token/:mint
 */
app.get('/token/:mint', async (req, res) => {
  const { mint } = req.params;
  if (!mint || mint.length < 32) {
    return res.status(400).json({ error: 'Invalid mint address' });
  }

  const urls = [
    `https://gmgn.ai/defi/quotation/v1/token/sol/${mint}`,
    `https://gmgn.ai/defi/quotation/v1/tokens/sol/${mint}`,
  ];

  for (const url of urls) {
    try {
      const data = await gmgnGet(url);
      if (data) {
        console.log(`Token OK: ${mint.slice(0, 12)} | code=${data.code ?? 'n/a'}`);
        return res.json(data);
      }
    } catch (err) {
      console.warn(`Token ${mint.slice(0, 12)} error: ${err.message}`);
    }
  }

  // POST endpoint sebagai fallback
  try {
    const response = await axios.post(
      'https://gmgn.ai/api/v1/mutil_window_token_info',
      { chain: 'sol', addresses: [mint] },
      {
        headers: { ...gmgnHeaders(), 'content-type': 'application/json' },
        timeout: 12_000,
      }
    );
    const data = response.data;
    if (data?.code === 0 && Array.isArray(data?.data) && data.data.length > 0) {
      return res.json({ code: 0, data: data.data[0] });
    }
  } catch (err) {
    console.warn(`Token POST fallback error: ${err.message}`);
  }

  return res.status(502).json({ error: 'GMGN unreachable', mint });
});

/**
 * GET /new_tokens
 */
app.get('/new_tokens', async (req, res) => {
  try {
    const data = await gmgnGet(
      'https://gmgn.ai/defi/quotation/v1/rank/sol/new_creation/1h' +
      '?limit=50&orderby=created_timestamp&direction=desc'
    );
    return res.json(data);
  } catch (err) {
    console.error(`new_tokens error: ${err.message}`);
    return res.status(502).json({ error: err.message });
  }
});

/**
 * GET /pump_rank
 */
app.get('/pump_rank', async (req, res) => {
  try {
    const data = await gmgnGet(
      'https://gmgn.ai/defi/quotation/v1/rank/sol/pump_rank/1h' +
      '?limit=50&orderby=volume&direction=desc&filters[]=not_wash_trading'
    );
    return res.json(data);
  } catch (err) {
    console.error(`pump_rank error: ${err.message}`);
    return res.status(502).json({ error: err.message });
  }
});

// ── Start ────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`✅ GMGN Bridge running on port ${PORT} (axios)`);
  console.log(`   GMGN_API_KEY: ${process.env.GMGN_API_KEY ? 'SET' : 'not set'}`);
});
