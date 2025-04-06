const Queue = require('bull');
const { queueSizeGauge } = require('./monitoring');
const Redis = require('ioredis');

// Konfigurasi Redis
const redisConfig = {
  host: process.env.REDIS_HOST || 'localhost',
  port: process.env.REDIS_PORT || 6379,
  password: process.env.REDIS_PASSWORD,
  tls: process.env.REDIS_TLS === 'true' ? {} : undefined
};

// Buat koneksi Redis
const redisClient = new Redis(redisConfig);

// Buat antrian unduhan dengan Redis
const downloadQueue = new Queue('media-downloads', {
  redis: redisConfig,
  limiter: {
    max: 5, // Maksimal 5 job berjalan bersamaan
    duration: 1000, // Dalam 1 detik
  },
});

// Update metrik ukuran antrian setiap kali ada perubahan
downloadQueue.on('global:waiting', async () => {
  const jobCounts = await downloadQueue.getJobCounts();
  queueSizeGauge.set(jobCounts.waiting);
});

// Proses antrian
downloadQueue.process(async (job) => {
  // Distribusikan job ke worker yang tersedia
  try {
    return await global.distributeJob(job.data);
  } catch (error) {
    console.error(`Error processing job ${job.id}:`, error);
    throw error;
  }
});

// Tangani error
downloadQueue.on('failed', (job, err) => {
  console.error(`Job ${job.id} failed with error: ${err.message}`);
});

// Tangani job yang selesai
downloadQueue.on('completed', (job, result) => {
  console.log(`Job ${job.id} completed with result:`, result);
});

// Ekspor antrian dan klien Redis
module.exports = { 
  downloadQueue,
  redisClient
};
