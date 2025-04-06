const express = require('express');
const router = express.Router();
const { exec, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const { downloadQueue } = require('../queue');
const { infoLimiter, downloadLimiter, statusLimiter } = require('../middleware/rateLimiter');
const { getCachedMediaInfo, cacheMediaInfo, getCachedDownload, cacheDownloadResult } = require('../services/cache');
const { createDownloadCircuitBreaker } = require('../services/circuitBreaker');
const { downloadCounter, downloadDuration } = require('../monitoring');

// Helper function untuk exec promise
function execPromise(command) {
  return new Promise((resolve, reject) => {
    exec(command, (error, stdout, stderr) => {
      if (error) reject(error);
      else resolve({ stdout, stderr });
    });
  });
}

// Endpoint untuk mendapatkan info media
router.post('/info', infoLimiter, async (req, res) => {
  const { url } = req.body;
  
  if (!url) {
    return res.status(400).json({ error: 'URL is required' });
  }
  
  try {
    const cachedInfo = await getCachedMediaInfo(url);
    if (cachedInfo) {
      return res.json(cachedInfo);
    }
    
    const command = `yt-dlp -J "${url}"`;
    const { stdout } = await execPromise(command);
    const info = JSON.parse(stdout);
    
    cacheMediaInfo(url, info);
    res.json(info);
  } catch (error) {
    console.error('Error in /info endpoint:', error);
    res.status(500).json({ error: error.message });
  }
});

// Endpoint untuk queue download (tetap simpan ke server)
router.post('/download', downloadLimiter, async (req, res) => {
  const { url, format, customName, subtitleOptions } = req.body;
  
  if (!url || !format) {
    return res.status(400).json({ error: 'URL and format are required' });
  }
  
  downloadCounter.inc({ status: 'requested' });
  
  try {
    const cachedDownload = await getCachedDownload(url, format);
    if (cachedDownload) {
      downloadCounter.inc({ status: 'cache_hit' });
      return res.json(cachedDownload);
    }
    
    const endTimer = downloadDuration.startTimer();
    const { stdout } = await execPromise(
      `yt-dlp --skip-download --print filename -o "%(title)s.%(ext)s" "${url}"`
    );
    
    const fileExt = format.split(' ')[0].split('+')[0];
    const filename = customName 
      ? `${customName}.${fileExt}`
      : stdout.trim();
    
    const downloadId = uuidv4();
    const outputPath = path.join(__dirname, '../temp', downloadId, filename);
    
    if (!fs.existsSync(path.dirname(outputPath))) {
      fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    }
    
    const job = await downloadQueue.add({
      id: uuidv4(),
      url,
      format,
      outputPath,
      customName,
      subtitleOptions,
      downloadId
    }, {
      attempts: 3,
      backoff: { type: 'exponential', delay: 5000 },
      removeOnComplete: true,
      removeOnFail: false
    });
    
    endTimer({ status: 'queued' });
    downloadCounter.inc({ status: 'queued' });
    
    const result = { 
      jobId: job.id, 
      downloadId, 
      filename,
      message: 'Download added to queue' 
    };
    
    cacheDownloadResult(url, format, result);
    res.json(result);
  } catch (error) {
    console.error('Error in /download endpoint:', error);
    downloadCounter.inc({ status: 'failed' });
    res.status(500).json({ error: error.message });
  }
});

// Endpoint baru untuk direct streaming
router.post('/stream', downloadLimiter, async (req, res) => {
  const { url, format } = req.body;
  
  if (!url || !format) {
    return res.status(400).json({ error: 'URL and format are required' });
  }
  
  downloadCounter.inc({ status: 'stream_requested' });
  const endTimer = downloadDuration.startTimer();
  
  try {
    const info = await getCachedMediaInfo(url) || 
                 await getFreshMediaInfo(url);
    
    const safeTitle = (info.title || 'download').replace(/[^a-z0-9]/gi, '_');
    const fileExt = format.split(' ')[0].split('+')[0];
    
    res.setHeader('Content-Disposition', `attachment; filename="${safeTitle}.${fileExt}"`);
    res.setHeader('Content-Type', 'application/octet-stream');

    const ytdlp = spawn('yt-dlp', [
      '-f', format,
      '-o', '-',
      '--no-cache-dir',
      '--no-simulate',
      url
    ]);

    ytdlp.stdout.pipe(res);
    
    ytdlp.stderr.on('data', (data) => {
      console.error(`Stream error: ${data}`);
    });

    ytdlp.on('error', (error) => {
      console.error('Process error:', error);
      if (!res.headersSent) res.status(500).end();
    });

    ytdlp.on('close', (code) => {
      endTimer({ status: code === 0 ? 'streamed' : 'stream_failed' });
      downloadCounter.inc({ status: code === 0 ? 'streamed' : 'stream_failed' });
    });

    res.on('close', () => ytdlp.kill());
    
  } catch (error) {
    console.error('Stream failed:', error);
    endTimer({ status: 'stream_failed' });
    downloadCounter.inc({ status: 'stream_failed' });
    if (!res.headersSent) res.status(500).json({ error: error.message });
  }
});

// Endpoint untuk status download
router.get('/status/:jobId', statusLimiter, async (req, res) => {
  const { jobId } = req.params;
  try {
    const job = await downloadQueue.getJob(jobId);
    if (!job) return res.status(404).json({ error: 'Job not found' });
    
    const state = await job.getState();
    res.json({
      jobId,
      state,
      progress: job.progress,
      data: job.data
    });
  } catch (error) {
    console.error('Error in /status endpoint:', error);
    res.status(500).json({ error: error.message });
  }
});

// Endpoint untuk download file yang sudah selesai
router.get('/download/:downloadId/:filename', async (req, res) => {
  const { downloadId, filename } = req.params;
  const filePath = path.join(__dirname, '../temp', downloadId, filename);
  
  if (fs.existsSync(filePath)) {
    res.download(filePath, filename, (err) => {
      if (err) {
        console.error('Download error:', err);
        res.status(500).json({ error: 'Download failed' });
      }
    });
    downloadCounter.inc({ status: 'downloaded' });
  } else {
    res.status(404).json({ error: 'File not found' });
    downloadCounter.inc({ status: 'file_not_found' });
  }
});

// Endpoint untuk cancel download
router.delete('/download/:jobId', async (req, res) => {
  const { jobId } = req.params;
  try {
    const job = await downloadQueue.getJob(jobId);
    if (!job) return res.status(404).json({ error: 'Job not found' });
    
    await job.remove();
    if (job.returnvalue?.outputPath) {
      const dir = path.dirname(job.returnvalue.outputPath);
      if (fs.existsSync(dir)) fs.rmSync(dir, { recursive: true });
    }
    
    res.json({ message: 'Download cancelled' });
    downloadCounter.inc({ status: 'cancelled' });
  } catch (error) {
    console.error('Cancel error:', error);
    res.status(500).json({ error: error.message });
  }
});

async function getFreshMediaInfo(url) {
  const { stdout } = await execPromise(`yt-dlp -j "${url}"`);
  const info = JSON.parse(stdout);
  cacheMediaInfo(url, info);
  return info;
}

module.exports = router;