const { parentPort } = require('worker_threads');
const { exec, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const { promisify } = require('util');
const stream = require('stream');
const pipeline = promisify(stream.pipeline);

parentPort.postMessage({ type: 'ready' });

parentPort.on('message', async (message) => {
  if (message.type === 'job') {
    try {
      const result = await processDownload(message.data);
      parentPort.postMessage({
        type: 'result',
        jobId: message.data.id,
        result
      });
    } catch (error) {
      parentPort.postMessage({
        type: 'error',
        jobId: message.data.id,
        error: error.message
      });
    }
  }
});

async function processDownload(job) {
  const { url, format, outputPath, subtitleOptions, downloadId } = job;
  const dir = path.dirname(outputPath);
  
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const args = [
    '-f', format,
    '-o', outputPath,
    '--no-simulate'
  ];

  if (subtitleOptions?.language) {
    args.push('--write-sub', '--sub-lang', subtitleOptions.language);
    if (subtitleOptions.format === 'srt') {
      args.push('--convert-subs', 'srt');
    }
  }

  args.push(url);

  return new Promise((resolve, reject) => {
    const process = spawn('yt-dlp', args);
    let progress = 0;

    process.stdout.on('data', (data) => {
      const progressMatch = data.toString().match(/(\d+(\.\d+)?)%/);
      if (progressMatch) {
        progress = parseFloat(progressMatch[1]);
        parentPort.postMessage({
          type: 'progress',
          jobId: job.id,
          progress
        });
      }
    });

    process.stderr.on('data', (data) => {
      console.error(`Download error: ${data}`);
    });

    process.on('close', (code) => {
      if (code === 0) {
        const stats = fs.statSync(outputPath);
        resolve({
          success: true,
          outputPath,
          downloadId,
          fileSize: stats.size,
          progress: 100
        });
      } else {
        reject(new Error(`Process exited with code ${code}`));
      }
    });

    process.on('error', reject);
  });
}

// Fungsi untuk streaming download (opsional)
async function streamDownload(job) {
  const { url, format } = job;
  const chunks = [];
  
  return new Promise((resolve, reject) => {
    const process = spawn('yt-dlp', [
      '-f', format,
      '-o', '-',
      '--no-cache-dir',
      url
    ]);

    process.stdout.on('data', (chunk) => {
      chunks.push(chunk);
      parentPort.postMessage({
        type: 'progress',
        jobId: job.id,
        progress: (chunks.length / (chunks.length + 1)) * 100
      });
    });

    process.on('close', (code) => {
      if (code === 0) {
        resolve({
          success: true,
          buffer: Buffer.concat(chunks),
          downloadId: job.downloadId
        });
      } else {
        reject(new Error(`Process exited with code ${code}`));
      }
    });

    process.on('error', reject);
  });
}