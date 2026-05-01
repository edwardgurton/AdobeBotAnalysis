const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const botValidationRsidList = require('./usefulInfo/Legend/botValidationRsidList');
const retrieveLegendRsid = require('./utils/retrieveLegendRsid');

/**
 * Downloads final bot rule metrics by iterating through all clean names, retrieving their RSIDs, and processing segment requests
 * @param {string} segmentsFilePath - Path to the segments JSON file
 * @param {string} jobName - Name of the job for file naming
 * @param {number} delay - Delay between requests in milliseconds
 * @param {string} fromDate - Start date (YYYY-MM-DD format)
 * @param {string} toDate - End date (YYYY-MM-DD format)
 * @param {string} requestName - Name of the request
 * @param {string} clientName - Client name
 * @param {string} interval - Time interval ('day', 'week', 'month')
 */
async function downloadFinalBotRuleMetrics(segmentsFilePath, jobName, delay = 0, fromDate, toDate, requestName, clientName, interval = 'day') {
  console.log(`\n=== Starting downloadFinalBotRuleMetrics ===`);
  console.log(`Total clean names to process: ${botValidationRsidList.length}`);
  console.log(`Segments file: ${segmentsFilePath}`);
  console.log(`Job name: ${jobName}`);
  console.log(`Date range: ${fromDate} to ${toDate}`);
  console.log(`Request name: ${requestName}`);
  console.log(`Client: ${clientName}`);
  console.log(`Interval: ${interval}`);
  console.log(`Delay: ${delay}ms`);
  console.log(`==========================================\n`);

  const results = {
    total: botValidationRsidList.length,
    completed: 0,
    failed: 0,
    retried: 0,
    errors: []
  };

  // Process each clean name sequentially
  for (let i = 0; i < botValidationRsidList.length; i++) {
    const cleanName = botValidationRsidList[i];
    const currentIndex = i + 1;
    
    console.log(`\n--- Processing clean name ${currentIndex}/${results.total}: ${cleanName} ---`);
    
    let rsid = null;
    let success = false;
    let lastError = null;
    
    // First, retrieve the RSID from the clean name
    try {
      console.log(`  Retrieving RSID for clean name: ${cleanName}`);
      rsid = await retrieveLegendRsid(cleanName);
      console.log(`  Retrieved RSID: ${rsid}`);
    } catch (error) {
      results.failed++;
      results.errors.push({
        cleanName: cleanName,
        rsid: 'N/A',
        index: currentIndex,
        error: `Failed to retrieve RSID: ${error.message}`
      });
      console.error(`✗ Failed to retrieve RSID for clean name ${cleanName}: ${error.message}`);
      console.log(`Progress: ${results.completed}/${results.total} completed, ${results.failed} failed, ${results.retried} retries used`);
      continue;
    }
    
    // Try twice (initial attempt + 1 retry)
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        if (attempt > 1) {
          console.log(`  Retrying clean name ${cleanName} (RSID: ${rsid}) (attempt ${attempt}/2)...`);
          results.retried++;
        }
        
        await processRsidWithChildProcess(segmentsFilePath, jobName, delay, fromDate, toDate, requestName, clientName, interval, rsid, cleanName);
        
        success = true;
        results.completed++;
        console.log(`✓ Successfully completed clean name ${currentIndex}/${results.total}: ${cleanName} (RSID: ${rsid})${attempt > 1 ? ' (after retry)' : ''}`);
        break;
        
      } catch (error) {
        lastError = error;
        console.error(`✗ Attempt ${attempt}/2 failed for clean name ${cleanName} (RSID: ${rsid}): ${error.message}`);
        
        if (attempt < 2) {
          console.log(`  Will retry clean name ${cleanName} (RSID: ${rsid})...`);
        }
      }
    }
    
    if (!success) {
      results.failed++;
      results.errors.push({
        cleanName: cleanName,
        rsid: rsid,
        index: currentIndex,
        error: lastError.message
      });
      console.error(`✗ Final failure for clean name ${currentIndex}/${results.total}: ${cleanName} (RSID: ${rsid}) after 2 attempts`);
    }
    
    console.log(`Progress: ${results.completed}/${results.total} completed, ${results.failed} failed, ${results.retried} retries used`);
  }

  // Final summary
  console.log(`\n=== Final Summary ===`);
  console.log(`Total clean names processed: ${results.total}`);
  console.log(`Successfully completed: ${results.completed}`);
  console.log(`Failed (after retries): ${results.failed}`);
  console.log(`Total retries used: ${results.retried}`);
  
  if (results.errors.length > 0) {
    console.log(`\n--- Failed Clean Names (after 2 attempts each) ---`);
    results.errors.forEach(({ cleanName, rsid, index, error }) => {
      console.log(`${index}. ${cleanName} (RSID: ${rsid}): ${error}`);
    });
  }
  
  console.log(`\n=== downloadFinalBotRuleMetrics completed ===`);
  
  return results;
}

/**
 * Processes a single RSID using a child process to handle the process.exit() in iterateSegmentRequests
 */
function processRsidWithChildProcess(segmentsFilePath, jobName, delay, fromDate, toDate, requestName, clientName, interval, rsid, cleanName) {
  return new Promise((resolve, reject) => {
    // Create inline worker script content
    const workerScript = `
const iterateSegmentRequests = require('./utils/iterateSegmentRequests');

// Parse command line arguments
const args = process.argv.slice(2);

if (args.length !== 10) {
  console.error('Usage: node worker.js <segmentsFilePath> <jobName> <delay> <fromDate> <toDate> <requestName> <clientName> <interval> <rsid> <cleanName>');
  process.exit(1);
}

const [
  segmentsFilePath,
  jobName,
  delay,
  fromDate,
  toDate,
  requestName,
  clientName,
  interval,
  rsid,
  cleanName
] = args;

// Convert delay to number
const delayMs = parseInt(delay, 10);

// Combine jobName with cleanName
const combinedJobName = \`\${jobName}_\${cleanName}\`;

console.log(\`Worker process started for clean name with RSID: \${rsid}\`);
console.log(\`Combined job name: \${combinedJobName}\`);

// Call iterateSegmentRequests - it will handle its own process.exit()
iterateSegmentRequests(
  segmentsFilePath,
  combinedJobName,
  delayMs,
  fromDate,
  toDate,
  requestName,
  clientName,
  interval,
  rsid
).catch(error => {
  console.error(\`Worker process error for RSID \${rsid}:\`, error);
  process.exit(1);
});
`;

    // Write temporary worker script
    const tempWorkerPath = path.join(__dirname, `temp_worker_${rsid.replace(/[^a-zA-Z0-9]/g, '_')}_${Date.now()}.js`);
    
    fs.writeFileSync(tempWorkerPath, workerScript);
    
    const child = spawn('node', [
      tempWorkerPath,
      segmentsFilePath,
      jobName,
      delay.toString(),
      fromDate,
      toDate,
      requestName,
      clientName,
      interval,
      rsid,
      cleanName
    ], {
      stdio: 'inherit' // This allows us to see the logs from the child process
    });

    child.on('close', (code) => {
      // Clean up temporary file
      try {
        fs.unlinkSync(tempWorkerPath);
      } catch (cleanupError) {
        console.warn(`Warning: Could not clean up temporary file ${tempWorkerPath}:`, cleanupError.message);
      }
      
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Child process exited with code ${code}`));
      }
    });

    child.on('error', (error) => {
      // Clean up temporary file on error
      try {
        fs.unlinkSync(tempWorkerPath);
      } catch (cleanupError) {
        // Ignore cleanup errors when main error occurred
      }
      
      reject(new Error(`Failed to start child process: ${error.message}`));
    });
  });
}

module.exports = downloadFinalBotRuleMetrics;