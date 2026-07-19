/**
 * portal — the paylane front end.
 *
 * Renders the payment form and the payment list. Talks to payment-svc,
 * mandate-svc, and ledger-svc over HTTP. Holds no data of its own.
 */
const express = require('express');
const axios = require('axios');
const path = require('path');
const client = require('prom-client');

const PORT = process.env.PORT || 3000;
const PAYMENT_SVC_URL = process.env.PAYMENT_SVC_URL || 'http://localhost:3002';
const MANDATE_SVC_URL = process.env.MANDATE_SVC_URL || 'http://localhost:3001';
const LEDGER_SVC_URL = process.env.LEDGER_SVC_URL || 'http://localhost:3003';

const app = express();
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, '..', 'views'));

// Prometheus metrics.
const register = new client.Registry();
client.collectDefaultMetrics({ register });
const httpRequests = new client.Counter({
  name: 'portal_http_requests_total',
  help: 'HTTP requests handled by the portal',
  labelNames: ['method', 'route', 'status'],
  registers: [register],
});

app.use((req, res, next) => {
  res.on('finish', () => {
    httpRequests.inc({ method: req.method, route: req.path, status: res.statusCode });
  });
  next();
});

app.get('/health', async (req, res) => {
  res.json({ status: 'ok', service: 'portal' });
});

app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

app.get('/', async (req, res) => {
  try {
    const [mandates, payments] = await Promise.all([
      axios.get(`${MANDATE_SVC_URL}/mandates`, { timeout: 5000 }),
      axios.get(`${PAYMENT_SVC_URL}/payments?limit=10`, { timeout: 5000 }),
    ]);
    res.render('index', {
      mandates: mandates.data.mandates,
      payments: payments.data.payments,
      error: null,
    });
  } catch (err) {
    res.status(503).render('index', { mandates: [], payments: [], error: err.message });
  }
});

app.post('/pay', async (req, res) => {
  const { mandate_ref, amount_rupees, idempotency_key } = req.body;
  try {
    await axios.post(
      `${PAYMENT_SVC_URL}/payments`,
      {
        mandate_ref,
        amount_paise: Math.round(parseFloat(amount_rupees) * 100),
        idempotency_key: idempotency_key || null,
      },
      { timeout: 5000 }
    );
    res.redirect('/');
  } catch (err) {
    const detail = err.response?.data?.detail || err.message;
    res.status(400).send(`Payment rejected: ${detail} — <a href="/">back</a>`);
  }
});

app.get('/accounts', async (req, res) => {
  try {
    const accounts = await axios.get(`${LEDGER_SVC_URL}/accounts`, { timeout: 5000 });
    res.render('accounts', { accounts: accounts.data.accounts });
  } catch (err) {
    res.status(503).send(`ledger-svc unavailable: ${err.message}`);
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`portal listening on :${PORT}`);
});
