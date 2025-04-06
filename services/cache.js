const { redisClient } = require('../queue');

// Cache TTL: 24 jam (dalam detik)
const CACHE_TTL = 86400;

/**
 * Simpan hasil unduhan ke cache
 * @param {string} url - URL media
 * @param {string} format - Format yang dipilih
 * @param {object} result - Hasil unduhan
 */
async function cacheDownloadResult(url, format, result) {
  try {
    const key = `download:${url}:${format}`;
    await redisClient.set(key, JSON.stringify(result), 'EX', CACHE_TTL);
    console.log(`Cached result for ${url} with format ${format}`);
  } catch (error) {
    console.error('Error caching download result:', error);
  }
}

/**
 * Cek apakah URL sudah pernah diunduh dengan format yang sama
 * @param {string} url - URL media
 * @param {string} format - Format yang dipilih
 * @returns {object|null} - Hasil unduhan dari cache atau null jika tidak ada
 */
async function getCachedDownload(url, format) {
  try {
    const key = `download:${url}:${format}`;
    const cached = await redisClient.get(key);
    if (cached) {
      console.log(`Cache hit for ${url} with format ${format}`);
      return JSON.parse(cached);
    }
    return null;
  } catch (error) {
    console.error('Error getting cached download:', error);
    return null;
  }
}

/**
 * Simpan info media ke cache
 * @param {string} url - URL media
 * @param {object} info - Info media
 */
async function cacheMediaInfo(url, info) {
  try {
    const key = `info:${url}`;
    await redisClient.set(key, JSON.stringify(info), 'EX', CACHE_TTL);
    console.log(`Cached info for ${url}`);
  } catch (error) {
    console.error('Error caching media info:', error);
  }
}

/**
 * Dapatkan info media dari cache
 * @param {string} url - URL media
 * @returns {object|null} - Info media dari cache atau null jika tidak ada
 */
async function getCachedMediaInfo(url) {
  try {
    const key = `info:${url}`;
    const cached = await redisClient.get(key);
    if (cached) {
      console.log(`Cache hit for info ${url}`);
      return JSON.parse(cached);
    }
    return null;
  } catch (error) {
    console.error('Error getting cached media info:', error);
    return null;
  }
}

module.exports = {
  cacheDownloadResult,
  getCachedDownload,
  cacheMediaInfo,
  getCachedMediaInfo
};
