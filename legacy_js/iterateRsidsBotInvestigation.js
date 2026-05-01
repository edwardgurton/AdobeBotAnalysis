// botInvestigationRsidsProcessor.js
const fs = require('fs');
const path = require('path');
const subtractDays = require('./utils/subtractDays.js');
const retrieveValue = require('./utils/retrieveValue.js');
const downloadBotInvestigationData = require('./downloadBotInvestigationData.js');
const rateLimitManager = require('./utils/RateLimitManager.js');

/**
 * Process bot investigation data for RSIDs (without country segmentation)
 * 
 * @param {Object} config - Configuration object
 * @param {string} config.toDate - End date in 'YYYY-MM-DD' format
 * @param {string} [config.mode='subtractDays'] - Mode for determining fromDate: 'subtractDays' or 'fixedFromDate'
 * @param {number} [config.subtractDaysValue=130] - Number of days to subtract from toDate (used when mode='subtractDays')
 * @param {string} [config.fromDate] - Start date in 'YYYY-MM-DD' format (used when mode='fixedFromDate')
 * @param {number} [config.investigationRound=1.0] - Investigation round number for naming
 * @param {Array<string>} [config.rsidCleanNameList] - Array of RSID clean names to process
 * @param {string} [config.rsidListPath] - Path to file containing RSID list (used if rsidCleanNameList not provided)
 * @param {string} [config.legendRsidLookupPath='./usefulInfo/Legend/legendReportSuites.txt'] - Path to legend RSID lookup file
 * @param {string} [config.logDir='./temp'] - Directory for log files
 * @param {boolean} [config.enableStatusReporting=true] - Enable periodic status reporting
 * @param {number} [config.statusReportingInterval=30000] - Status reporting interval in milliseconds
 * 
 * @returns {Promise<Object>} Result object containing:
 *   - {boolean} success - Whether all processing completed successfully
 *   - {number} processed - Number of RSIDs successfully processed
 *   - {number} failed - Number of RSIDs that failed
 *   - {Array} errors - Array of error details for failed items
 *   - {string} logFilePath - Path to the log file
 *   - {number} runNumber - The run number for this execution
 * 
 * @example
 * // Example 1: Using subtract days mode (default)
 * const result = await processBotInvestigationRsids({
 *   toDate: '2025-05-31',
 *   mode: 'subtractDays',
 *   subtractDaysValue: 130,
 *   investigationRound: 4.2,
 *   rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js'
 * });
 * 
 * @example
 * // Example 2: Using fixed from date mode
 * const result = await processBotInvestigationRsids({
 *   toDate: '2025-05-31',
 *   mode: 'fixedFromDate',
 *   fromDate: '2025-01-01',
 *   investigationRound: 4.2,
 *   rsidCleanNameList: ['OnlineSlotsca', 'Casinoguru', 'ExampleSite']
 * });
 * 
 * @example
 * // Example 3: Single RSID with custom configuration
 * const result = await processBotInvestigationRsids({
 *   toDate: '2025-05-31',
 *   rsidCleanNameList: ['OnlineSlotsca'],
 *   logDir: './logs/single-rsid',
 *   enableStatusReporting: false
 * });
 */
async function processBotInvestigationRsids(config) {
    // Validate and set defaults
    const settings = {
        toDate: config.toDate,
        mode: config.mode || 'subtractDays',
        subtractDaysValue: config.subtractDaysValue || 130,
        fromDate: config.fromDate,
        investigationRound: config.investigationRound || 1.0,
        rsidCleanNameList: config.rsidCleanNameList,
        rsidListPath: config.rsidListPath || './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
        legendRsidLookupPath: config.legendRsidLookupPath || './usefulInfo/Legend/legendReportSuites.txt',
        logDir: config.logDir || './temp',
        enableStatusReporting: config.enableStatusReporting !== false,
        statusReportingInterval: config.statusReportingInterval || 30000
    };

    // Validate required parameters
    if (!settings.toDate) {
        throw new Error('toDate is required');
    }

    if (settings.mode === 'fixedFromDate' && !settings.fromDate) {
        throw new Error('fromDate is required when mode is "fixedFromDate"');
    }

    if (settings.mode !== 'subtractDays' && settings.mode !== 'fixedFromDate') {
        throw new Error('mode must be either "subtractDays" or "fixedFromDate"');
    }

    // Calculate fromDate based on mode
    let fromDate;
    if (settings.mode === 'subtractDays') {
        fromDate = subtractDays(settings.toDate, settings.subtractDaysValue);
    } else {
        fromDate = settings.fromDate;
    }

    // Load RSID list
    let rsidCleanNameList;
    if (settings.rsidCleanNameList) {
        rsidCleanNameList = settings.rsidCleanNameList;
    } else {
        try {
            rsidCleanNameList = require(settings.rsidListPath);
        } catch (error) {
            throw new Error(`Failed to load RSID list from ${settings.rsidListPath}: ${error.message}`);
        }
    }

    // Setup logging
    const tempRunNumber = Math.floor(Math.random() * 1000000);
    const logFileName = `BotInvestigationRsids_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    const logFilePath = path.join(settings.logDir, logFileName);

    // Ensure log directory exists
    if (!fs.existsSync(settings.logDir)) {
        fs.mkdirSync(settings.logDir, { recursive: true });
    }

    // Initialize log file
    fs.writeFileSync(logFilePath, `Bot Investigation RSIDs Log - Run ${tempRunNumber}\n`);
    fs.appendFileSync(logFilePath, `Started at: ${new Date().toISOString()}\n`);
    fs.appendFileSync(logFilePath, `Configuration:\n`);
    fs.appendFileSync(logFilePath, `  - To Date: ${settings.toDate}\n`);
    fs.appendFileSync(logFilePath, `  - From Date: ${fromDate}\n`);
    fs.appendFileSync(logFilePath, `  - Mode: ${settings.mode}\n`);
    fs.appendFileSync(logFilePath, `  - Investigation Round: ${settings.investigationRound}\n`);
    fs.appendFileSync(logFilePath, `  - RSIDs to process: ${rsidCleanNameList.length}\n\n`);

    // Logging function
    function logToFile(message) {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] ${message}\n`;
        fs.appendFileSync(logFilePath, logEntry);
        console.log(message);
    }

    // Process single RSID
    async function processRsid(rsidCleanName) {
        const suiteName = rsidCleanName;
        const rsid = retrieveValue(settings.legendRsidLookupPath, suiteName, 'right');
        const investigationName = `${suiteName}-FullRun-V${settings.investigationRound}`;

        try {
            logToFile(`🚀 Starting: ${suiteName} (RSID: ${rsid})`);
            await downloadBotInvestigationData(
                0,
                fromDate,
                settings.toDate,
                'Legend',
                undefined,  // No segment ID for RSID-only processing
                rsid,
                investigationName
            );
            logToFile(`✅ Completed: ${suiteName} (RSID: ${rsid})`);
            return { success: true };
        } catch (error) {
            logToFile(`❌ Error processing ${suiteName} (RSID: ${rsid}): ${error.message}`);
            return { 
                success: false, 
                error: {
                    rsidCleanName: suiteName,
                    rsid,
                    message: error.message
                }
            };
        }
    }

    // Main processing logic
    const results = {
        success: true,
        processed: 0,
        failed: 0,
        errors: [],
        logFilePath,
        runNumber: tempRunNumber
    };

    logToFile(`📊 Processing ${rsidCleanNameList.length} RSIDs sequentially with centralized rate limiting (Run ${tempRunNumber})`);
    console.log(`📁 Log file: ${logFilePath}`);

    // Setup status reporting if enabled
    let statusInterval;
    if (settings.enableStatusReporting) {
        statusInterval = setInterval(() => {
            const status = rateLimitManager.getStatus();
            if (status.queueLength > 0 || status.activeRequests > 0) {
                console.log(`📈 Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}, Rate: ${status.rateLimit.requestsInWindow}/${status.rateLimit.maxRequestsPerWindow} per ${status.rateLimit.windowSizeSeconds}s${status.isPaused ? `, Paused until: ${status.pauseUntil}` : ''}`);
            }
        }, settings.statusReportingInterval);
    }

    try {
        // Process each RSID
        for (let i = 0; i < rsidCleanNameList.length; i++) {
            const rsidCleanName = rsidCleanNameList[i];
            console.log(`\n📋 Processing RSID ${i + 1}/${rsidCleanNameList.length}: ${rsidCleanName}`);
            
            const result = await processRsid(rsidCleanName);
            
            if (result.success) {
                results.processed++;
            } else {
                results.failed++;
                results.errors.push(result.error);
                results.success = false;
            }
            
            // Brief status check between RSIDs
            const status = rateLimitManager.getStatus();
            console.log(`📊 Queue: ${status.queueLength}, Active: ${status.activeRequests}, Rate: ${status.rateLimit.requestsInWindow}/${status.rateLimit.maxRequestsPerWindow}`);
        }

        // Wait for remaining requests
        console.log("\n⏳ Waiting for remaining requests to complete...");
        while (rateLimitManager.getStatus().activeRequests > 0 || rateLimitManager.getStatus().queueLength > 0) {
            const status = rateLimitManager.getStatus();
            console.log(`📈 Final Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}`);
            await new Promise(resolve => setTimeout(resolve, 5000));
        }

        if (results.failed === 0) {
            logToFile("🎉 All RSIDs have been processed successfully!");
        } else {
            logToFile(`⚠️ Processing completed with ${results.failed} failures out of ${rsidCleanNameList.length} RSIDs`);
        }

    } catch (error) {
        logToFile(`💥 An error occurred during processing: ${error.message}`);
        results.success = false;
        throw error;
    } finally {
        if (statusInterval) {
            clearInterval(statusInterval);
        }
        
        // Clean up rate limit manager
        logToFile("🧹 Cleaning up rate limit manager...");
        rateLimitManager.destroy();
    }

    logToFile(`\n📊 Final Results:`);
    logToFile(`  - Total RSIDs: ${rsidCleanNameList.length}`);
    logToFile(`  - Processed successfully: ${results.processed}`);
    logToFile(`  - Failed: ${results.failed}`);
    logToFile(`  - Success rate: ${((results.processed / rsidCleanNameList.length) * 100).toFixed(2)}%`);
    logToFile(`Completed at: ${new Date().toISOString()}\n`);

    return results;
}

// Export the main function
module.exports = processBotInvestigationRsids;

// Execute when run directly
if (require.main === module) {
    // Configuration - modify these values as needed
    const config = {
        toDate: '2025-08-31',
        mode: 'fixedFromDate',
        fromDate: '2025-05-01',
        subtractDaysValue: 90,
        investigationRound: 4.4,
        rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
        //rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js'
        //rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js',
        //rsidCleanNames: ['Casinous'],
        //countries: ['United States', 'China', 'Canada', 'United Kingdom', 'Brazil', 'Singapore', 'Germany','TypoForTesting'],
    };

    // Run the processor
    processBotInvestigationRsids(config)
        .then(result => {
            console.log('\n✨ Processing complete!');
            console.log('Results:', result);
            process.exit(result.success ? 0 : 1);
        })
        .catch(error => {
            console.error('💥 Fatal error:', error);
            process.exit(1);
        });
}