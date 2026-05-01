// botInvestigationProcessor.js
const fs = require('fs');
const path = require('path');
const subtractDays = require('./utils/subtractDays.js');
const retrieveValue = require('./utils/retrieveValue.js');
const downloadBotInvestigationData = require('./downloadBotInvestigationData.js');
const rateLimitManager = require('./utils/RateLimitManager.js');

/**
 * Process bot investigation data for RSID/Country combinations
 * 
 * @param {Object} config - Configuration object
 * @param {string} config.toDate - End date in 'YYYY-MM-DD' format
 * @param {string} [config.mode='subtractDays'] - Mode for determining fromDate: 'subtractDays' or 'fixedFromDate'
 * @param {number} [config.subtractDaysValue=130] - Number of days to subtract from toDate (used when mode='subtractDays')
 * @param {string} [config.fromDate] - Start date in 'YYYY-MM-DD' format (used when mode='fixedFromDate')
 * @param {number} [config.investigationRound=1.0] - Version number for investigation naming
 * @param {Array} [config.rsidCountriesList] - Array of RSID/Country objects to process
 * @param {string} [config.rsidCountriesListPath] - Path to file containing RSID/Country list (used if rsidCountriesList not provided)
 * @param {Array<string>} [config.rsidCleanNames] - Optional array of rsidCleanName values to filter by (only matching items will be processed)
 * @param {Array<string>} [config.countries] - Optional array of country names to filter by (only matching items will be processed)
 * @param {string} [config.legendRsidLookupPath='./usefulInfo/Legend/legendReportSuites.txt'] - Path to legend RSID lookup file
 * @param {string} [config.logDir='./temp'] - Directory for log files
 * @param {boolean} [config.enableStatusReporting=true] - Enable periodic status reporting
 * @param {number} [config.statusReportingInterval=30000] - Status reporting interval in milliseconds
 * 
 * @returns {Promise<Object>} Result object containing:
 *   - {boolean} success - Whether all processing completed successfully
 *   - {number} processed - Number of items successfully processed
 *   - {number} failed - Number of items that failed
 *   - {Array} errors - Array of error details for failed items
 *   - {string} logFilePath - Path to the log file
 *   - {number} runNumber - The run number for this execution
 * 
 * @example
 * // Example 1: Using subtract days mode (default)
 * const result = await processBotInvestigation({
 *   toDate: '2025-05-31',
 *   mode: 'subtractDays',
 *   subtractDaysValue: 130,
 *   investigationRound: 4.0,
 *   rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js'
 * });
 * 
 * @example
 * // Example 2: Using fixed from date mode
 * const result = await processBotInvestigation({
 *   toDate: '2025-05-31',
 *   mode: 'fixedFromDate',
 *   fromDate: '2025-01-01',
 *   investigationRound: 4.0,
 *   rsidCountriesList: [
 *     {
 *       rsidCleanName: "Casinoguru",
 *       geocountry: "South Africa",
 *       segmentId: "s3938_68528652e90051508f05779d",
 *       visits: 323603
 *     }
 *   ]
 * });
 * 
 * @example
 * // Example 3: Minimal configuration with custom logging
 * const result = await processBotInvestigation({
 *   toDate: '2025-05-31',
 *   logDir: './logs/bot-investigation',
 *   enableStatusReporting: false
 * });
 * 
 * @example
 * // Example 4: Using filters to process specific RSIDs and countries
 * const result = await processBotInvestigation({
 *   toDate: '2025-05-31',
 *   mode: 'subtractDays',
 *   subtractDaysValue: 130,
 *   investigationRound: 4.0,
 *   rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js',
 *   rsidCleanNames: ['Apuestasdeportivascom', 'Casinoguru'],  // Only process these RSIDs
 *   countries: ['Spain', 'Peru']  // Only process these countries
 * });
 */
async function processBotInvestigation(config) {
    // Validate and set defaults
    const settings = {
        toDate: config.toDate,
        mode: config.mode || 'subtractDays',
        subtractDaysValue: config.subtractDaysValue || 130,
        fromDate: config.fromDate,
        investigationRound: config.investigationRound || 1.0,
        rsidCountriesList: config.rsidCountriesList,
        rsidCountriesListPath: config.rsidCountriesListPath || './usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js',
        rsidCleanNames: config.rsidCleanNames,
        countries: config.countries,
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

    // Load RSID countries list
    let rsidCountriesList;
    if (settings.rsidCountriesList) {
        rsidCountriesList = settings.rsidCountriesList;
    } else {
        try {
            rsidCountriesList = require(settings.rsidCountriesListPath);
        } catch (error) {
            throw new Error(`Failed to load RSID countries list from ${settings.rsidCountriesListPath}: ${error.message}`);
        }
    }

    // Apply filters if specified
    const originalCount = rsidCountriesList.length;
    if (settings.rsidCleanNames && Array.isArray(settings.rsidCleanNames) && settings.rsidCleanNames.length > 0) {
        rsidCountriesList = rsidCountriesList.filter(item => settings.rsidCleanNames.includes(item.rsidCleanName));
    }
    if (settings.countries && Array.isArray(settings.countries) && settings.countries.length > 0) {
        rsidCountriesList = rsidCountriesList.filter(item => settings.countries.includes(item.geocountry));
    }
    const filteredCount = rsidCountriesList.length;
    
    if (filteredCount === 0) {
        throw new Error('No RSID/Country combinations match the specified filters');
    }

    // Setup logging
    const tempRunNumber = Math.floor(Math.random() * 1000000);
    const logFileName = `BotInvestigationRsidCountries_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    const logFilePath = path.join(settings.logDir, logFileName);

    // Ensure log directory exists
    if (!fs.existsSync(settings.logDir)) {
        fs.mkdirSync(settings.logDir, { recursive: true });
    }

    // Initialize log file
    fs.writeFileSync(logFilePath, `Bot Investigation RSID Countries Log - Run ${tempRunNumber}\n`);
    fs.appendFileSync(logFilePath, `Started at: ${new Date().toISOString()}\n`);
    fs.appendFileSync(logFilePath, `Configuration:\n`);
    fs.appendFileSync(logFilePath, `  - To Date: ${settings.toDate}\n`);
    fs.appendFileSync(logFilePath, `  - From Date: ${fromDate}\n`);
    fs.appendFileSync(logFilePath, `  - Mode: ${settings.mode}\n`);
    fs.appendFileSync(logFilePath, `  - Version: ${settings.investigationRound}\n`);
    if (settings.rsidCleanNames && settings.rsidCleanNames.length > 0) {
        fs.appendFileSync(logFilePath, `  - Filtered by RSID Clean Names: ${settings.rsidCleanNames.join(', ')}\n`);
    }
    if (settings.countries && settings.countries.length > 0) {
        fs.appendFileSync(logFilePath, `  - Filtered by Countries: ${settings.countries.join(', ')}\n`);
    }
    if (originalCount !== filteredCount) {
        fs.appendFileSync(logFilePath, `  - Items after filtering: ${filteredCount} (from ${originalCount})\n`);
    } else {
        fs.appendFileSync(logFilePath, `  - Items to process: ${rsidCountriesList.length}\n`);
    }
    fs.appendFileSync(logFilePath, `\n`);

    // Logging function
    function logToFile(message) {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] ${message}\n`;
        fs.appendFileSync(logFilePath, logEntry);
        console.log(message);
    }

    // Process single RSID/Country combination
    async function processRsidCountry(rsidCountryData) {
        const { rsidCleanName, geocountry, segmentId, visits } = rsidCountryData;
        const suiteName = rsidCleanName;
        const rsid = retrieveValue(settings.legendRsidLookupPath, suiteName, 'right');
        const investigationName = `${suiteName}-${geocountry}-FullRun-V${settings.investigationRound}`;

        try {
            logToFile(`🚀 Starting: ${suiteName} - ${geocountry} (RSID: ${rsid}, Segment: ${segmentId}, Visits: ${visits.toLocaleString()})`);
            await downloadBotInvestigationData(
                0,
                fromDate,
                settings.toDate,
                'Legend',
                segmentId,
                rsid,
                investigationName
            );
            logToFile(`✅ Completed: ${suiteName} - ${geocountry} (RSID: ${rsid})`);
            return { success: true };
        } catch (error) {
            logToFile(`❌ Error processing ${suiteName} - ${geocountry} (RSID: ${rsid}): ${error.message}`);
            return { 
                success: false, 
                error: {
                    rsidCleanName: suiteName,
                    geocountry,
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

    logToFile(`📊 Processing ${rsidCountriesList.length} RSID/Country combinations sequentially with centralized rate limiting (Run ${tempRunNumber})`);
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
        // Process each RSID/Country combination
        for (let i = 0; i < rsidCountriesList.length; i++) {
            const rsidCountryData = rsidCountriesList[i];
            console.log(`\n📋 Processing ${i + 1}/${rsidCountriesList.length}: ${rsidCountryData.rsidCleanName} - ${rsidCountryData.geocountry} (${rsidCountryData.visits.toLocaleString()} visits)`);
            
            const result = await processRsidCountry(rsidCountryData);
            
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
            logToFile("🎉 All RSID/Country combinations have been processed successfully!");
        } else {
            logToFile(`⚠️ Processing completed with ${results.failed} failures out of ${rsidCountriesList.length} items`);
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
    logToFile(`  - Total items: ${rsidCountriesList.length}`);
    logToFile(`  - Processed successfully: ${results.processed}`);
    logToFile(`  - Failed: ${results.failed}`);
    logToFile(`  - Success rate: ${((results.processed / rsidCountriesList.length) * 100).toFixed(2)}%`);
    logToFile(`Completed at: ${new Date().toISOString()}\n`);

    return results;
}

// Export the main function
module.exports = processBotInvestigation;

// Also export a helper to create a standalone executable version
module.exports.createStandaloneScript = function(config) {
    return `
const processBotInvestigation = require('./botInvestigationProcessor');

// Configuration
const config = ${JSON.stringify(config, null, 2)};

// Run the processor
processBotInvestigation(config)
    .then(result => {
        console.log('\\n✨ Processing complete!');
        console.log('Results:', result);
        process.exit(result.success ? 0 : 1);
    })
    .catch(error => {
        console.error('💥 Fatal error:', error);
        process.exit(1);
    });
`;
};
// Execute when run directly
if (require.main === module) {
    // Configuration - modify these values as needed
    const config = {
        toDate: '2026-01-19',
        mode: 'subtractDays',
        fromDate: '2025-02-01',
        subtractDaysValue: 90,
        investigationRound: 4.7,
        rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js',
        //rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js',
        rsidCleanNames: ['Oddspediacom'],
        countries: ['Singapore', 'Hong Kong SAR of China']
    };

    // Run the processor
    processBotInvestigation(config)
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