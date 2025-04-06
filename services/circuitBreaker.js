const CircuitBreaker = require('opossum');

// Konfigurasi circuit breaker
const options = {
  failureThreshold: 50,    // Jika 50% permintaan gagal
  resetTimeout: 30000,     // Tunggu 30 detik sebelum mencoba lagi
  timeout: 300000,         // Timeout setelah 5 menit
  errorThresholdPercentage: 50
};

/**
 * Buat circuit breaker untuk fungsi unduhan
 * @param {Function} downloadFunction - Fungsi yang akan dilindungi oleh circuit breaker
 * @returns {CircuitBreaker} - Instance circuit breaker
 */
function createDownloadCircuitBreaker(downloadFunction) {
  const breaker = new CircuitBreaker(downloadFunction, options);
  
  breaker.on('open', () => {
    console.log('Circuit Breaker is now OPEN - stopping all download requests');
  });
  
  breaker.on('halfOpen', () => {
    console.log('Circuit Breaker is now HALF-OPEN - testing if service is available');
  });
  
  breaker.on('close', () => {
    console.log('Circuit Breaker is now CLOSED - service is available');
  });
  
  breaker.on('fallback', (result) => {
    console.log('Circuit Breaker fallback called');
  });
  
  breaker.fallback(() => {
    return { error: 'Service is currently unavailable. Please try again later.' };
  });
  
  return breaker;
}

module.exports = {
  createDownloadCircuitBreaker
};
