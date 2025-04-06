const fs = require('fs');
const path = require('path');
const schedule = require('node-schedule');

// Bersihkan folder temp
function cleanupTemp() {
  const tempDir = path.join(__dirname, '../temp');
  if (!fs.existsSync(tempDir)) return;

  console.log('[Cleanup] Running temp folder cleanup...');
  const now = Date.now();
  const oneHour = 60 * 60 * 1000;

  fs.readdirSync(tempDir).forEach(folder => {
    const folderPath = path.join(tempDir, folder);
    try {
      const stat = fs.statSync(folderPath);
      
      // Hapus folder yang lebih dari 1 jam
      if (now - stat.mtimeMs > oneHour) {
        fs.rmSync(folderPath, { recursive: true, force: true });
        console.log(`[Cleanup] Deleted old folder: ${folder}`);
      }
    } catch (error) {
      console.error(`[Cleanup] Error cleaning ${folder}:`, error);
    }
  });
}

// Bersihkan folder downloads permanen
function cleanupDownloads() {
  const downloadsDir = path.join(__dirname, '../downloads');
  if (!fs.existsSync(downloadsDir)) return;

  console.log('[Cleanup] Running downloads folder cleanup...');
  const now = Date.now();
  const twentyFourHours = 24 * 60 * 60 * 1000;

  fs.readdirSync(downloadsDir).forEach(folder => {
    const folderPath = path.join(downloadsDir, folder);
    try {
      const stat = fs.statSync(folderPath);
      if (now - stat.mtimeMs > twentyFourHours) {
        fs.rmSync(folderPath, { recursive: true, force: true });
        console.log(`[Cleanup] Deleted old download: ${folder}`);
      }
    } catch (error) {
      console.error(`[Cleanup] Error cleaning ${folder}:`, error);
    }
  });
}

// Jadwalkan pembersihan
function scheduleCleanup() {
  // Setiap jam pada menit ke-30
  schedule.scheduleJob('30 * * * *', () => {
    cleanupTemp();
    cleanupDownloads();
  });
  
  // Jalankan saat startup
  cleanupTemp();
  cleanupDownloads();
  console.log('[Cleanup] Scheduled cleanup jobs');
}

module.exports = {
  cleanupTemp,
  cleanupDownloads,
  scheduleCleanup
};