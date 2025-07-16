// server.js
const express = require('express');
const crypto = require('crypto');
const axios = require('axios');
const cors = require('cors');
const app = express();

app.use(cors());           // Allow all origins; restrict in production!
app.use(express.json());

function sign(queryString, secret) {
  return crypto
    .createHmac('sha256', secret)
    .update(queryString)
    .digest('hex');
}

async function binanceProxy(route, method, key, secret, params, body = {}) {
  const timestamp = Date.now();
  const query = new URLSearchParams({...params, timestamp}).toString();
  const signature = sign(query, secret);

  const url = `https://api.binance.com${route}?${query}&signature=${signature}`;
  return axios({
    url,
    method,
    headers: { 'X-MBX-APIKEY': key },
    data: body
  });
}

// Proxy for all needed routes
app.post('/api/proxy', async (req, res) => {
  try {
    const { route, method, key, secret, params, body } = req.body;
    const result = await binanceProxy(route, method, key, secret, params, body);
    res.json(result.data);
  } catch (e) {
    res.status(500).json({ error: e.message, data: e?.response?.data });
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log(`Backend running on port ${PORT}`));
