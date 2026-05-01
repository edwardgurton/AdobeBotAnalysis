const fs = require('fs');
const path = require('path');
const retrieveValue = require('./utils/retrieveValue.js');
const botRuleCompareAcrossSuspiciousDimensions = require('./downloadBotRuleCompare.js');
const rateLimitManager = require('./utils/RateLimitManager.js');

/**
 * Mapping from short dimension names (as used in CSV) to full report names
 */
const DIMENSION_MAPPING = {
    'UserAgent': 'botInvestigationMetricsByUserAgent',
    'Region': 'botInvestigationMetricsByRegion',
    'MonitorResolution': 'botInvestigationMetricsByMonitorResolution',
    'PageURL': 'botInvestigationMetricsByPageURL',
    'Domain': 'botInvestigationMetricsByDomain',
    'BrowserType': 'botInvestigationMetricsByBrowserType',
    'OperatingSystem': 'botInvestigationMetricsByOperatingSystem',
    'Operating System': 'botInvestigationMetricsByOperatingSystem',
    'MobileManufacturer': 'botInvestigationMetricsByMobileManufacturer',
    'HourOfDay': 'botInvestigationMetricsByHourOfDay',
    'MarketingChannel': 'botInvestigationMetricsByMarketingChannel',
    'ReferringDomain': 'botInvestigationMetricsByMarketingChannel',
    'Marketing Channel': 'botInvestigationMetricsByMarketingChannel',
    'Referring Domain': 'botInvestigationMetricsByMarketingChannel',
};

/**
 * Parse CSV file containing bot rule configurations
 * 
 * @param {string} csvFilePath - Path to the CSV file
 * @returns {Array<Object>} Array of bot rule configurations
 */
function parseBotRuleCsv(csvFilePath) {
    const csvContent = fs.readFileSync(csvFilePath, 'utf8');
    const lines = csvContent.split('\n').filter(line => line.trim());
    
    if (lines.length < 2) {
        throw new Error('CSV file must contain a header row and at least one data row');
    }
    
    // Parse header
    const header = lines[0].replace(/^\uFEFF/, '').split(',').map(h => h.trim());
    const segmentIdIndex = header.indexOf('DimSegmentId');
    const botRuleNameIndex = header.indexOf('botRuleName');
    const reportToIgnoreIndex = header.indexOf('reportToIgnore');
    
    if (segmentIdIndex === -1 || botRuleNameIndex === -1 || reportToIgnoreIndex === -1) {
        throw new Error('CSV must contain columns: DimSegmentId, botRuleName, reportToIgnore');
    }
    
    // Parse data rows
    const rules = [];
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const values = line.split(',').map(v => v.trim());
        const segmentId = values[segmentIdIndex];
        const botRuleName = values[botRuleNameIndex];
        const reportToIgnoreShort = values[reportToIgnoreIndex];
        
        // Map short dimension name to full report name
        const reportToSkip = DIMENSION_MAPPING[reportToIgnoreShort];
        if (!reportToSkip) {
            console.warn(`Warning: Unknown dimension "${reportToIgnoreShort}" in row ${i + 1}. Using as-is.`);
        }
        
        rules.push({
            segmentId,
            segmentName: botRuleName,
            reportToSkip: reportToSkip || `botInvestigationMetricsBy${reportToIgnoreShort}`
        });
    }
    
    return rules;
}

/**
 * Process bot rule comparison data for multiple RSIDs
 * 
 * This function iterates through a list of RSIDs and compares bot rule segment traffic
 * against all traffic across suspicious dimensions (excluding the dimension used in the rule).
 * 
 * @param {Object} config - Configuration object
 * @param {string} config.fromDate - Start date in 'YYYY-MM-DD' format
 * @param {string} config.toDate - End date in 'YYYY-MM-DD' format (should be following day for bot investigation)
 * 
 * ===== CSV BATCH MODE =====
 * @param {boolean} [config.csvBatchMode] - Enable CSV batch processing mode
 * @param {string} [config.csvFileName] - CSV filename in '../usefulInfo/Legend/BotCompareLists' directory
 *   CSV must have columns: DimSegmentId, botRuleName, reportToIgnore
 *   When csvBatchMode is true, segmentId, segmentName, and reportToSkip are ignored
 * 
 * ===== SINGLE RULE MODE =====
 * @param {string} [config.reportToSkip] - Full report name to skip (the dimension used in the bot rule)
 * @param {string} [config.segmentId] - Adobe Analytics segment ID for the bot rule
 * @param {string} [config.segmentName] - Human-readable name for the segment (used in file naming)
 * @param {Array<Object>} [config.rsidConfigList] - Array of RSID configuration objects with format:
 *   [{cleanName: 'OnlineSlotsca', segmentId: 'xxx', segmentName: 'Rule1'}, ...]
 *   If provided, each RSID can have its own segment configuration
 * 
 * ===== RSID CONFIGURATION (Used by all modes) =====
 * @param {Array<string>} [config.rsidCleanNameList] - Array of RSID clean names to process
 * @param {string} [config.rsidListPath] - Path to file containing RSID list
 * 
 * ===== COMMON SETTINGS =====
 * @param {number} [config.comparisonRound=1.0] - Comparison round number for naming
 * @param {string} [config.legendRsidLookupPath='./usefulInfo/Legend/legendReportSuites.txt'] - Path to legend RSID lookup file
 * @param {string} [config.clientName='Legend'] - Client name for Adobe API
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
 * // Example 1: CSV Batch Processing (NEW!)
 * const result = await processBotRuleComparison({
 *   fromDate: '2025-02-01',
 *   toDate: '2025-05-31',
 *   csvBatchMode: true,
 *   csvFileName: 'BotCompareFebMay25.csv',
 *   comparisonRound: 1.0,
 *   rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js'
 * });
 * 
 * @example
 * // Example 2: Single segment applied to all RSIDs
 * const result = await processBotRuleComparison({
 *   fromDate: '2025-01-01',
 *   toDate: '2025-03-31',
 *   reportToSkip: 'botInvestigationMetricsByDomain',
 *   segmentId: 's3938_6780ffad8e0db45770364b00',
 *   segmentName: 'Philippines-Rule',
 *   comparisonRound: 1.0,
 *   rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js'
 * });
 * 
 * @example
 * // Example 3: Different segments per RSID
 * const result = await processBotRuleComparison({
 *   fromDate: '2025-01-01',
 *   toDate: '2025-03-31',
 *   reportToSkip: 'botInvestigationMetricsByDomain',
 *   comparisonRound: 1.0,
 *   rsidConfigList: [
 *     { cleanName: 'OnlineSlotsca', segmentId: 's123_abc', segmentName: 'Canada-Rule' },
 *     { cleanName: 'Casinoguru', segmentId: 's123_def', segmentName: 'Global-Rule' }
 *   ]
 * });
 * 
 * @example
 * // Example 4: Custom RSID list with shared segment
 * const result = await processBotRuleComparison({
 *   fromDate: '2025-01-01',
 *   toDate: '2025-03-31',
 *   reportToSkip: 'botInvestigationMetricsByUserAgent',
 *   segmentId: 's3938_xyz',
 *   segmentName: 'Suspicious-UA',
 *   rsidCleanNameList: ['OnlineSlotsca', 'Casinoguru', 'coverscom'],
 *   comparisonRound: 2.0
 * });
 */
async function processBotRuleComparison(config) {
    // Validate and set defaults
    const settings = {
        fromDate: config.fromDate,
        toDate: config.toDate,
        csvBatchMode: config.csvBatchMode || false,
        csvFileName: config.csvFileName,
        reportToSkip: config.reportToSkip,
        segmentId: config.segmentId,
        segmentName: config.segmentName,
        comparisonRound: config.comparisonRound || 1.0,
        rsidConfigList: config.rsidConfigList,
        rsidCleanNameList: config.rsidCleanNameList,
        rsidListPath: config.rsidListPath || './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
        legendRsidLookupPath: config.legendRsidLookupPath || './usefulInfo/Legend/legendReportSuites.txt',
        clientName: config.clientName || 'Legend',
        logDir: config.logDir || './temp',
        enableStatusReporting: config.enableStatusReporting !== false,
        statusReportingInterval: config.statusReportingInterval || 30000
    };

    // Validate required parameters
    if (!settings.fromDate || !settings.toDate) {
        throw new Error('fromDate and toDate are required');
    }

    // Load RSID list (needed for all modes)
    let rsidCleanNameList;
    if (settings.rsidCleanNameList) {
        rsidCleanNameList = settings.rsidCleanNameList;
    } else if (settings.rsidListPath) {
        try {
            rsidCleanNameList = require(settings.rsidListPath);
        } catch (error) {
            throw new Error(`Failed to load RSID list from ${settings.rsidListPath}: ${error.message}`);
        }
    } else {
        throw new Error('Either rsidCleanNameList or rsidListPath must be provided');
    }

    // Build processing list based on mode
    let processingList;
    let processingMode;
    
    if (settings.csvBatchMode) {
        // ===== CSV BATCH MODE =====
        if (!settings.csvFileName) {
            throw new Error('csvFileName is required when csvBatchMode is true');
        }
        
        const csvPath = path.join('./usefulInfo/Legend/BotCompareLists', settings.csvFileName);
        console.log(`📄 Loading bot rules from CSV: ${csvPath}`);
        
        try {
            const botRules = parseBotRuleCsv(csvPath);
            console.log(`✅ Loaded ${botRules.length} bot rules from CSV`);
            
            // Create processing list: each rule × each RSID
            processingList = [];
            for (const rule of botRules) {
                for (const cleanName of rsidCleanNameList) {
                    processingList.push({
                        cleanName,
                        segmentId: rule.segmentId,
                        segmentName: rule.segmentName,
                        reportToSkip: rule.reportToSkip
                    });
                }
            }
            
            processingMode = 'CSV Batch';
            console.log(`📋 Processing ${botRules.length} rules across ${rsidCleanNameList.length} RSIDs = ${processingList.length} total comparisons`);
            
        } catch (error) {
            throw new Error(`Failed to load CSV file: ${error.message}`);
        }
        
    } else {
        // ===== SINGLE RULE MODE (existing functionality) =====
        if (!settings.reportToSkip) {
            throw new Error('reportToSkip is required when csvBatchMode is false');
        }
        
        const hasRsidConfigList = settings.rsidConfigList && settings.rsidConfigList.length > 0;
        const hasSharedSegment = settings.segmentId && settings.segmentName;

        if (!hasRsidConfigList && !hasSharedSegment) {
            throw new Error('Either rsidConfigList OR (segmentId + segmentName) must be provided');
        }
        
        if (hasRsidConfigList) {
            // Use provided RSID config list with individual segments
            processingList = settings.rsidConfigList.map(config => ({
                cleanName: config.cleanName,
                segmentId: config.segmentId,
                segmentName: config.segmentName,
                reportToSkip: settings.reportToSkip
            }));
            processingMode = 'RSID-specific segments';
            console.log('📋 Using RSID-specific segment configurations');
        } else {
            // Apply shared segment to all RSIDs
            processingList = rsidCleanNameList.map(cleanName => ({
                cleanName,
                segmentId: settings.segmentId,
                segmentName: settings.segmentName,
                reportToSkip: settings.reportToSkip
            }));
            processingMode = 'Shared segment';
            console.log(`📋 Applying shared segment (${settings.segmentName}) to all RSIDs`);
        }
    }

    // Setup logging
    const tempRunNumber = Math.floor(Math.random() * 1000000);
    const logFileName = `BotRuleComparison_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    const logFilePath = path.join(settings.logDir, logFileName);

    // Ensure log directory exists
    if (!fs.existsSync(settings.logDir)) {
        fs.mkdirSync(settings.logDir, { recursive: true });
    }

    // Initialize log file
    fs.writeFileSync(logFilePath, `Bot Rule Comparison Log - Run ${tempRunNumber}\n`);
    fs.appendFileSync(logFilePath, `Started at: ${new Date().toISOString()}\n`);
    fs.appendFileSync(logFilePath, `Configuration:\n`);
    fs.appendFileSync(logFilePath, `  - Processing Mode: ${processingMode}\n`);
    fs.appendFileSync(logFilePath, `  - From Date: ${settings.fromDate}\n`);
    fs.appendFileSync(logFilePath, `  - To Date: ${settings.toDate}\n`);
    fs.appendFileSync(logFilePath, `  - Comparison Round: ${settings.comparisonRound}\n`);
    fs.appendFileSync(logFilePath, `  - Total comparisons to process: ${processingList.length}\n`);
    if (settings.csvBatchMode) {
        fs.appendFileSync(logFilePath, `  - CSV File: ${settings.csvFileName}\n`);
    } else if (!hasRsidConfigList) {
        fs.appendFileSync(logFilePath, `  - Shared Segment: ${settings.segmentName} (${settings.segmentId})\n`);
        fs.appendFileSync(logFilePath, `  - Report to Skip: ${settings.reportToSkip}\n`);
    }
    fs.appendFileSync(logFilePath, `\n`);

    // Logging function
    function logToFile(message) {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] ${message}\n`;
        fs.appendFileSync(logFilePath, logEntry);
        console.log(message);
    }

    // Process single comparison (RSID + Rule combination)
    async function processComparison(item) {
        const { cleanName, segmentId, segmentName, reportToSkip } = item;
        const rsid = retrieveValue(settings.legendRsidLookupPath, cleanName, 'right');
        const investigationName = `${cleanName}-${segmentName}-Compare-V${settings.comparisonRound}`;

        try {
            logToFile(`🚀 Starting: ${cleanName} (RSID: ${rsid}, Segment: ${segmentName}, Skip: ${reportToSkip})`);
            await botRuleCompareAcrossSuspiciousDimensions(
                settings.fromDate,
                settings.toDate,
                reportToSkip,
                segmentId,
                segmentName,
                rsid,
                cleanName,
                settings.clientName,
                investigationName
            );
            logToFile(`✅ Completed: ${cleanName} (RSID: ${rsid}, Segment: ${segmentName})`);
            return { success: true };
        } catch (error) {
            logToFile(`❌ Error processing ${cleanName} (RSID: ${rsid}, Segment: ${segmentName}): ${error.message}`);
            return {
                success: false,
                error: {
                    rsidCleanName: cleanName,
                    rsid,
                    ruleName: segmentName,
                    segmentId,
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

    logToFile(`📊 Processing ${processingList.length} comparisons sequentially with centralized rate limiting (Run ${tempRunNumber})`);
    console.log(`📝 Log file: ${logFilePath}`);

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
        // Process each comparison
        for (let i = 0; i < processingList.length; i++) {
            const item = processingList[i];
            console.log(`\n📋 Processing comparison ${i + 1}/${processingList.length}: ${item.cleanName} × ${item.segmentName}`);

            const result = await processComparison(item);

            if (result.success) {
                results.processed++;
            } else {
                results.failed++;
                results.errors.push(result.error);
                results.success = false;
            }

            // Brief status check between comparisons
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
            logToFile("🎉 All comparisons have been processed successfully!");
        } else {
            logToFile(`⚠️  Processing completed with ${results.failed} failures out of ${processingList.length} comparisons`);
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
    logToFile(`  - Total comparisons: ${processingList.length}`);
    logToFile(`  - Processed successfully: ${results.processed}`);
    logToFile(`  - Failed: ${results.failed}`);
    logToFile(`  - Success rate: ${((results.processed / processingList.length) * 100).toFixed(2)}%`);
    logToFile(`Completed at: ${new Date().toISOString()}\n`);

    return results;
}

// Export the main function
module.exports = processBotRuleComparison;

// Helper to create a standalone executable script
module.exports.createStandaloneScript = function(config) {
    return `
const processBotRuleComparison = require('./processBotRuleComparison');

// Configuration
const config = ${JSON.stringify(config, null, 2)};

// Run the processor
processBotRuleComparison(config)
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