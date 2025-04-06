const rateLimit = require('express-rate-limit');
const RedisStore = require('rate-limit-redis');
const { redisClient } = require('../queue');

// Rate limiter untuk API info
const infoLimiter = rateLimit({
  store: new RedisStore({
    sendCommand: (...args) => redisClient.call(...args),
    prefix: 'ratelimit:info:'
  }),
  windowMs: 1 * 60 * 1000, // 1 menit
  max: 30, // 30 permintaan per menit
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: 'Too many requests, please try again later.'
  }
});

// Rate limiter untuk API download (lebih ketat)
const downloadLimiter = rateLimit({
  store: new RedisStore({
    sendCommand: (...args) => redisClient.call(...args),
    prefix: 'ratelimit:download:'
  }),
  windowMs: 5 * 60 * 1000, // 5 menit
  max: 5, // 5 permintaan per 5 menit
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: 'Download limit reached. Please try again later.'
  }
});

// Rate limiter untuk API status
const statusLimiter = rateLimit({
  store: new RedisStore({
    sendCommand: (...args) => redisClient.call(...args),
    prefix: 'ratelimit:status:'
  }),
  windowMs: 1 * 60 * 1000, // 1 menit
  max: 60, // 60 permintaan per menit
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: 'Too many status requests, please try again later.'
  }
});

module.exports = {
  infoLimiter,
  downloadLimiter,
  statusLimiter
};
