const prometheus = require('prom-client');
const register = new prometheus.Registry();

// Buat koleksi metrik default
prometheus.collectDefaultMetrics({ register });

// Metrik untuk jumlah permintaan unduhan
const downloadCounter = new prometheus.Counter({
  name: 'download_requests_total',
  help: 'Total number of download requests',
  labelNames: ['status']
});

// Metrik untuk waktu pemrosesan unduhan
const downloadDuration = new prometheus.Histogram({
  name: 'download_duration_seconds',
  help: 'Duration of download processing in seconds',
  labelNames: ['status'],
  buckets: [1, 5, 10, 30, 60, 120, 300, 600]
});

// Metrik untuk ukuran antrian
const queueSizeGauge = new prometheus.Gauge({
  name: 'download_queue_size',
  help: 'Current size of the download queue'
});

// Metrik untuk ukuran file yang diunduh
const downloadSizeHistogram = new prometheus.Histogram({
  name: 'download_size_bytes',
  help: 'Size of downloaded files in bytes',
  buckets: [
    1024 * 1024,        // 1MB
    10 * 1024 * 1024,   // 10MB
    50 * 1024 * 1024,   // 50MB
    100 * 1024 * 1024,  // 100MB
    500 * 1024 * 1024,  // 500MB
    1024 * 1024 * 1024, // 1GB
    2 * 1024 * 1024 * 1024 // 2GB
  ]
});

// Metrik untuk jumlah worker yang aktif
const activeWorkersGauge = new prometheus.Gauge({
  name: 'active_workers',
  help: 'Number of active download workers'
});

// Daftarkan metrik
register.registerMetric(downloadCounter);
register.registerMetric(downloadDuration);
register.registerMetric(queueSizeGauge);
register.registerMetric(downloadSizeHistogram);
register.registerMetric(activeWorkersGauge);

// Middleware untuk mengekspos metrik
function metricsMiddleware(req, res) {
  res.set('Content-Type', register.contentType);
  register.metrics().then(data => res.end(data));
}

module.exports = {
  downloadCounter,
  downloadDuration,
  queueSizeGauge,
  downloadSizeHistogram,
  activeWorkersGauge,
  metricsMiddleware
};
