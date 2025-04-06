const express = require('express');
const router = express.Router();
const { redisClient } = require('../queue');

// Endpoint untuk health check
router.get('/health', async (req, res) => {
  try {
    // Cek koneksi Redis
    await redisClient.ping();
    
    // Semua sistem berjalan dengan baik
    res.json({ status: 'ok', message: 'Service is healthy' });
  } catch (error) {
    console.error('Health check failed:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

module.exports = router;
