const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const downloadAdobeTable = require('./downloadAdobeTable.js');

/**
 * Get the storage folder path from config
 * @param {string} configPath - Path to read/write config file
 * @returns {string} Base storage folder path
 */
function getStorageFolder(configPath = './config/read_write_settings/readWriteSettings.yaml') {
    try {
        const config = yaml.load(fs.readFileSync(configPath, 'utf8'));
        const baseFolder = config.storage?.folder;
        if (!baseFolder) {
            throw new Error('Base folder is undefined in read/write configuration');
        }
        return baseFolder;
    } catch (error) {
        throw new Error(`Failed to load storage folder from config: ${error.message}`);
    }
}

/**
 * Generate the expected filename for a downloaded file
 * @param {string} clientName - Client name
 * @param {string} reportType - Report type
 * @param {string} investigationName - Investigation name
 * @param {string} suffix - 'Segment' or 'AllTraffic'
 * @param {string} fromDate - Start date
 * @param {string} toDate - End date
 * @param {string} [segmentId] - Segment ID (only for Segment files)
 * @returns {string} Expected filename
 */
function generateFilename(clientName, reportType, investigationName, suffix, fromDate, toDate, segmentId = null) {
    const fileNameExtraPart = `_${investigationName}-${suffix}`;
    const dimSegmentPart = segmentId ? `DIMSEG${segmentId}_` : '';
    return `${clientName}_${reportType}${fileNameExtraPart}_${dimSegmentPart}${fromDate}_${toDate}.json`;
}

/**
 * Generate full file path for a report
 * @param {string} baseFolder - Base storage folder
 * @param {string} clientName - Client name
 * @param {string} reportType - Report type
 * @param {string} investigationName - Investigation name
 * @param {string} suffix - 'Segment' or 'AllTraffic'
 * @param {string} fromDate - Start date
 * @param {string} toDate - End date
 * @param {string} [segmentId] - Segment ID (only for Segment files)
 * @returns {string} Full file path
 */
function generateFilePath(baseFolder, clientName, reportType, investigationName, suffix, fromDate, toDate, segmentId = null) {
    const jsonFolder = path.join(baseFolder, clientName, 'JSON');
    const filename = generateFilename(clientName, reportType, investigationName, suffix, fromDate, toDate, segmentId);
    return path.join(jsonFolder, filename);
}

/**
 * Check if an AllTraffic file exists for this report type, RSID, and date range
 * Returns the path to an existing file if found, null otherwise
 * 
 * @param {string} baseFolder - Base storage folder
 * @param {string} clientName - Client name  
 * @param {string} reportType - Report type
 * @param {string} fromDate - Start date
 * @param {string} toDate - End date
 * @returns {string|null} Path to existing AllTraffic file or null
 */
function findExistingAllTrafficFile(baseFolder, clientName, reportType, cleanName, fromDate, toDate) {
    const jsonFolder = path.join(baseFolder, clientName, 'JSON');
    
    if (!fs.existsSync(jsonFolder)) {
        return null;
    }
    
    // Pattern to match any AllTraffic file for this report/date combination
    // Example: Legend_botInvestigationMetricsByDomain_*-AllTraffic_2025-01-01_2025-03-31.json
    const pattern = new RegExp(
        `^${clientName}_${reportType}_${cleanName}-BOTCOMPARE.*-AllTraffic_${fromDate}_${toDate}\\.json$`
    );
    console.log("Searching For: ", pattern,"in", jsonFolder);
    
    const files = fs.readdirSync(jsonFolder);
    const matchingFile = files.find(file => pattern.test(file));
    
    if (matchingFile) {
        return path.join(jsonFolder, matchingFile);
    }
    
    return null;
}

/**
 * Copy an existing AllTraffic file with a new investigation name
 * 
 * @param {string} sourcePath - Path to existing file
 * @param {string} destPath - Path for new file
 * @returns {boolean} True if copy was successful
 */
function copyAllTrafficFile(sourcePath, destPath) {
    try {
        fs.copyFileSync(sourcePath, destPath);
        return true;
    } catch (error) {
        console.error(`   ❌ Failed to copy file: ${error.message}`);
        return false;
    }
}

/**
 * Download bot investigation data comparing segment traffic vs all traffic across suspicious dimensions
 * OPTIMIZED VERSION: Only downloads AllTraffic reports once, then copies them for subsequent runs
 * 
 * This function downloads data for 9/10 bot investigation dimensions (excluding one specified dimension).
 * Each dimension is requested twice:
 * 1. With the bot rule segment ID (suspected bot traffic) - ALWAYS DOWNLOADED
 * 2. Without segment ID (all traffic) - DOWNLOADED ONCE, then COPIED for subsequent runs
 * 
 * All download requests are made concurrently for efficiency.
 * 
 * @param {string} fromDate - Start date in 'YYYY-MM-DD' format
 * @param {string} toDate - End date in 'YYYY-MM-DD' format (should be following day for bot investigation)
 * @param {string} reportToSkip - Full report name to skip (the dimension used in the bot rule)
 *   Options: 'botInvestigationMetricsByMarketingChannel', 'botInvestigationMetricsByMobileManufacturer',
 *           'botInvestigationMetricsByDomain', 'botInvestigationMetricsByMonitorResolution',
 *           'botInvestigationMetricsByHourOfDay', 'botInvestigationMetricsByOperatingSystem',
 *           'botInvestigationMetricsByPageURL', 'botInvestigationMetricsByRegion',
 *           'botInvestigationMetricsByUserAgent', 'botInvestigationMetricsByBrowserType'
 * @param {string} segmentId - Adobe Analytics segment ID for the bot rule
 * @param {string} segmentName - Human-readable name for the segment (used in file naming)
 * @param {string} [rsid='default'] - Report Suite ID
 * @param {string} [clientName='Legend'] - Client name for Adobe API
 * @param {string} [investigationName] - Custom investigation name (if not provided, will be auto-generated)
 * @param {string} [configPath] - Path to read/write config file
 * 
 * @returns {Promise<Object>} Results object with download and copy statistics
 * 
 * @example
 * // Compare bot rule segment across all dimensions except Domain
 * const results = await botRuleCompareAcrossSuspiciousDimensions(
 *   '2025-01-01',
 *   '2025-03-31',
 *   'botInvestigationMetricsByDomain',
 *   's3938_6780ffad8e0db45770364b00',
 *   'Philippines-Rule',
 *   'coverscom-prod',
 *   'Legend',
 *   'Covers-Philippines-Comparison'
 * );
 * console.log(`Downloaded: ${results.downloaded}, Copied: ${results.copied}`);
 */
async function botRuleCompareAcrossSuspiciousDimensions(
    fromDate,
    toDate,
    reportToSkip,
    segmentId,
    segmentName,
    rsid = 'default',
    cleanName = undefined,
    clientName = 'Legend',
    investigationName = undefined,
    configPath = './config/read_write_settings/readWriteSettings.yaml'
) {
    // Validate inputs
    if (!fromDate || !toDate) {
        throw new Error('fromDate and toDate are required');
    }
    if (!reportToSkip) {
        throw new Error('reportToSkip is required');
    }
    if (!segmentId) {
        throw new Error('segmentId is required');
    }
    if (!segmentName) {
        throw new Error('segmentName is required');
    }

    // Define all available report types
    const allReportTypes = [
        'botInvestigationMetricsByMarketingChannel',
        'botInvestigationMetricsByMobileManufacturer',
        'botInvestigationMetricsByDomain',
        'botInvestigationMetricsByMonitorResolution',
        'botInvestigationMetricsByHourOfDay',
        'botInvestigationMetricsByOperatingSystem',
        'botInvestigationMetricsByPageURL',
        'botInvestigationMetricsByRegion',
        'botInvestigationMetricsByUserAgent',
        'botInvestigationMetricsByBrowserType'
    ];

    // Validate reportToSkip
    if (!allReportTypes.includes(reportToSkip)) {
        throw new Error(`Invalid reportToSkip: "${reportToSkip}". Must be one of: ${allReportTypes.join(', ')}`);
    }

    // Filter out the report to skip
    const reportsToRun = allReportTypes.filter(report => report !== reportToSkip);

    // Generate investigation name if not provided
    const finalInvestigationName = investigationName || `SegmentComparison-${segmentName}`;

    // Get storage folder for file path checks
    const baseFolder = getStorageFolder(configPath);

    // Initialize statistics
    const stats = {
        segmentDownloaded: 0,
        allTrafficDownloaded: 0,
        allTrafficCopied: 0,
        allTrafficFailed: 0
    };

    try {
        console.log(`\n🔍 Starting ${finalInvestigationName}`);
        console.log(`📊 Processing ${reportsToRun.length} dimensions (excluding ${reportToSkip})`);
        console.log(`🎯 Segment: ${segmentName} (${segmentId})`);
        console.log(`📅 Date Range: ${fromDate} to ${toDate}`);
        console.log(`🏢 RSID: ${rsid}`);
        console.log(`⚡ Checking for existing AllTraffic files to optimize downloads...\n`);

        const downloadPromises = [];
        const copyOperations = [];

        // Process each report type
        for (const reportType of reportsToRun) {
            // ===== SEGMENT FILES: Always download (unique per bot rule) =====
            downloadPromises.push(
                downloadAdobeTable(
                    fromDate,
                    toDate,
                    reportType,
                    clientName,
                    segmentId,  // With segment ID
                    rsid,
                    `${finalInvestigationName}-Segment`
                ).then(() => {
                    stats.segmentDownloaded++;
                })
            );

            // ===== ALL TRAFFIC FILES: Download once, then copy =====
            // Check if an AllTraffic file already exists for this report/date/rsid
            const existingAllTrafficFile = findExistingAllTrafficFile(
                baseFolder,
                clientName,
                reportType,
                cleanName,
                fromDate,
                toDate
            );

            const targetAllTrafficPath = generateFilePath(
                baseFolder,
                clientName,
                reportType,
                finalInvestigationName,
                'AllTraffic',
                fromDate,
                toDate
            );

            if (existingAllTrafficFile && fs.existsSync(existingAllTrafficFile)) {
                // File exists - copy it instead of downloading
                console.log(`   ♻️  Found existing: ${path.basename(existingAllTrafficFile)}`);
                console.log(`   📋 Copying to: ${path.basename(targetAllTrafficPath)}`);
                
                copyOperations.push({
                    source: existingAllTrafficFile,
                    dest: targetAllTrafficPath,
                    reportType
                });
            } else {
                // File doesn't exist - download it
                console.log(`   📥 Downloading: ${reportType} (AllTraffic)`);
                
                downloadPromises.push(
                    downloadAdobeTable(
                        fromDate,
                        toDate,
                        reportType,
                        clientName,
                        undefined,  // No segment ID (all traffic)
                        rsid,
                        `${finalInvestigationName}-AllTraffic`
                    ).then(() => {
                        stats.allTrafficDownloaded++;
                    })
                );
            }
        }

        // Execute all downloads concurrently
        if (downloadPromises.length > 0) {
            console.log(`\n⏳ Executing ${downloadPromises.length} downloads concurrently...`);
            await Promise.all(downloadPromises);
        }

        // Execute all copy operations
        if (copyOperations.length > 0) {
            console.log(`\n📋 Copying ${copyOperations.length} existing AllTraffic files...`);
            for (const op of copyOperations) {
                const success = copyAllTrafficFile(op.source, op.dest);
                if (success) {
                    console.log(`   ✅ Copied: ${op.reportType}`);
                    stats.allTrafficCopied++;
                } else {
                    console.log(`   ⚠️  Failed to copy ${op.reportType} - may need to download manually`);
                    stats.allTrafficFailed++;
                }
            }
        }

        // Summary
        console.log(`\n✅ ${finalInvestigationName} - Completed successfully`);
        console.log(`\n📊 Statistics:`);
        console.log(`   • Segment files downloaded: ${stats.segmentDownloaded}`);
        console.log(`   • AllTraffic files downloaded: ${stats.allTrafficDownloaded}`);
        console.log(`   • AllTraffic files copied: ${stats.allTrafficCopied}`);
        if (stats.allTrafficFailed > 0) {
            console.log(`   ⚠️  AllTraffic copy failures: ${stats.allTrafficFailed}`);
        }
        console.log(`   • Total files created: ${stats.segmentDownloaded + stats.allTrafficDownloaded + stats.allTrafficCopied}`);
        console.log(`   • API calls saved: ${stats.allTrafficCopied} 🎉\n`);

        return {
            success: true,
            segmentDownloaded: stats.segmentDownloaded,
            allTrafficDownloaded: stats.allTrafficDownloaded,
            allTrafficCopied: stats.allTrafficCopied,
            allTrafficFailed: stats.allTrafficFailed,
            totalFilesCreated: stats.segmentDownloaded + stats.allTrafficDownloaded + stats.allTrafficCopied
        };

    } catch (error) {
        console.error(`❌ ${finalInvestigationName} - An error occurred:`, error);
        throw error;
    }
}

module.exports = botRuleCompareAcrossSuspiciousDimensions;

// Example usage (commented out):
/*
const retrieveValue = require('./utils/retrieveValue.js');
const legendRsidList = './usefulInfo/Legend/legendReportSuites.txt';

const suite = 'coverscom';
const rsid = retrieveValue(legendRsidList, suite, 'right');
const segmentId = 's3938_6780ffad8e0db45770364b00';
const segmentName = 'Philippines-Rule';
const fromDate = '2025-01-01';
const toDate = '2025-03-31';
const reportToSkip = 'botInvestigationMetricsByDomain';

botRuleCompareAcrossSuspiciousDimensions(
    fromDate,
    toDate,
    reportToSkip,
    segmentId,
    segmentName,
    rsid,
    'Legend',
    `${suite}-${segmentName}-Comparison`
);
*/