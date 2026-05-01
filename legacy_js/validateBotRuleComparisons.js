const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const retrieveValue = require('./utils/retrieveValue.js');
const downloadAdobeTable = require('./downloadAdobeTable.js');
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
    'Country': 'botInvestigationMetricsByCountry',
    'City': 'botInvestigationMetricsByCity',
    'Browser': 'botInvestigationMetricsByBrowserType',
    'OperatingSystem': 'botInvestigationMetricsByOperatingSystem',
    'MobileDeviceType': 'botInvestigationMetricsByMobileManufacturer',
    'MarketingChannel': 'botInvestigationMetricsByMarketingChannel',
    'HourOfDay': 'botInvestigationMetricsByHourOfDay'
};

/**
 * Parse CSV file containing bot rule configurations
 */
function parseBotRuleCsv(csvFilePath) {
    const csvContent = fs.readFileSync(csvFilePath, 'utf8');
    const lines = csvContent.split('\n').filter(line => line.trim());
    
    if (lines.length < 2) {
        throw new Error('CSV file must contain a header row and at least one data row');
    }
    
    const header = lines[0].replace(/^\uFEFF/, '').split(',').map(h => h.trim());
    const segmentIdIndex = header.indexOf('DimSegmentId');
    const botRuleNameIndex = header.indexOf('botRuleName');
    const reportToIgnoreIndex = header.indexOf('reportToIgnore');
    
    if (segmentIdIndex === -1 || botRuleNameIndex === -1 || reportToIgnoreIndex === -1) {
        throw new Error('CSV must contain columns: DimSegmentId, botRuleName, reportToIgnore');
    }
    
    const rules = [];
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const values = line.split(',').map(v => v.trim());
        const segmentId = values[segmentIdIndex];
        const botRuleName = values[botRuleNameIndex];
        const reportToIgnoreShort = values[reportToIgnoreIndex];
        
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
 * Get list of all bot investigation report types
 */
function getAllReportTypes() {
    return [
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
}

/**
 * Generate expected filename for a report
 */
function generateFilename(baseFolder, clientName, reportType, investigationName, suffix, segmentId, fromDate, toDate) {
    const folderPath = path.join(baseFolder, clientName, 'JSON');
    const fileNameExtraPart = `_${investigationName}-${suffix}`;
    const dimSegmentPart = segmentId ? `DIMSEG${segmentId}_` : '';
    return path.join(folderPath, `${clientName}_${reportType}${fileNameExtraPart}_${dimSegmentPart}${fromDate}_${toDate}.json`);
}

/**
 * Get expected files for a single comparison
 */
function getExpectedFiles(baseFolder, clientName, fromDate, toDate, reportToSkip, segmentId, investigationName) {
    const allReports = getAllReportTypes();
    const reportsToCheck = allReports.filter(report => report !== reportToSkip);
    
    const expectedFiles = [];
    
    for (const reportType of reportsToCheck) {
        // File with segment (bot traffic)
        expectedFiles.push({
            path: generateFilename(baseFolder, clientName, reportType, investigationName, 'Segment', segmentId, fromDate, toDate),
            reportType,
            hasSegment: true,
            investigationName,
            segmentId,
            fromDate,
            toDate
        });
        
        // File without segment (all traffic)
        expectedFiles.push({
            path: generateFilename(baseFolder, clientName, reportType, investigationName, 'AllTraffic', null, fromDate, toDate),
            reportType,
            hasSegment: false,
            investigationName,
            segmentId: null,
            fromDate,
            toDate
        });
    }
    
    return expectedFiles;
}

/**
 * Validate and re-download missing files for bot rule comparisons
 * 
 * @param {Object} config - Configuration object (same structure as processBotRuleComparison)
 * @returns {Promise<Object>} Validation results
 */
async function validateBotRuleComparisons(config) {
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
        statusReportingInterval: config.statusReportingInterval || 30000,
        dryRun: config.dryRun || false,
        readWriteConfigPath: config.readWriteConfigPath || './config/read_write_settings/readWriteSettings.yaml'
    };

    // Load base folder from config
    let baseFolder;
    try {
        const readWriteConfig = yaml.load(fs.readFileSync(settings.readWriteConfigPath, 'utf8'));
        baseFolder = readWriteConfig.storage?.folder;
        if (!baseFolder) {
            throw new Error('Base folder is undefined in read/write configuration');
        }
    } catch (error) {
        throw new Error(`Failed to load read/write config: ${error.message}`);
    }

    // Validate required parameters
    if (!settings.fromDate || !settings.toDate) {
        throw new Error('fromDate and toDate are required');
    }

    // Load RSID list
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

    // Build validation list based on mode
    let validationList;
    let processingMode;
    
    if (settings.csvBatchMode) {
        // CSV BATCH MODE
        if (!settings.csvFileName) {
            throw new Error('csvFileName is required when csvBatchMode is true');
        }
        
        const csvPath = path.join('./usefulInfo/Legend/BotCompareLists', settings.csvFileName);
        console.log(`📄 Loading bot rules from CSV: ${csvPath}`);
        
        try {
            const botRules = parseBotRuleCsv(csvPath);
            console.log(`✅ Loaded ${botRules.length} bot rules from CSV`);
            
            validationList = [];
            for (const rule of botRules) {
                for (const cleanName of rsidCleanNameList) {
                    const rsid = retrieveValue(settings.legendRsidLookupPath, cleanName, 'right');
                    const investigationName = `${cleanName}-${rule.segmentName}-Compare-V${settings.comparisonRound}`;
                    
                    validationList.push({
                        cleanName,
                        rsid,
                        segmentId: rule.segmentId,
                        segmentName: rule.segmentName,
                        reportToSkip: rule.reportToSkip,
                        investigationName
                    });
                }
            }
            
            processingMode = 'CSV Batch';
            console.log(`📋 Validating ${botRules.length} rules across ${rsidCleanNameList.length} RSIDs = ${validationList.length} comparisons`);
            
        } catch (error) {
            throw new Error(`Failed to load CSV file: ${error.message}`);
        }
        
    } else {
        // SINGLE RULE MODE
        if (!settings.reportToSkip) {
            throw new Error('reportToSkip is required when csvBatchMode is false');
        }
        
        const hasRsidConfigList = settings.rsidConfigList && settings.rsidConfigList.length > 0;
        const hasSharedSegment = settings.segmentId && settings.segmentName;

        if (!hasRsidConfigList && !hasSharedSegment) {
            throw new Error('Either rsidConfigList OR (segmentId + segmentName) must be provided');
        }
        
        validationList = [];
        
        if (hasRsidConfigList) {
            for (const config of settings.rsidConfigList) {
                const rsid = retrieveValue(settings.legendRsidLookupPath, config.cleanName, 'right');
                const investigationName = `${config.cleanName}-${config.segmentName}-Compare-V${settings.comparisonRound}`;
                
                validationList.push({
                    cleanName: config.cleanName,
                    rsid,
                    segmentId: config.segmentId,
                    segmentName: config.segmentName,
                    reportToSkip: settings.reportToSkip,
                    investigationName
                });
            }
            processingMode = 'RSID-specific segments';
        } else {
            for (const cleanName of rsidCleanNameList) {
                const rsid = retrieveValue(settings.legendRsidLookupPath, cleanName, 'right');
                const investigationName = `${cleanName}-${settings.segmentName}-Compare-V${settings.comparisonRound}`;
                
                validationList.push({
                    cleanName,
                    rsid,
                    segmentId: settings.segmentId,
                    segmentName: settings.segmentName,
                    reportToSkip: settings.reportToSkip,
                    investigationName
                });
            }
            processingMode = 'Shared segment';
        }
    }

    // Setup logging
    const tempRunNumber = Math.floor(Math.random() * 1000000);
    const logFileName = `BotRuleValidation_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    const logFilePath = path.join(settings.logDir, logFileName);
    
    // Setup expected files output
    const expectedFilesFileName = `BotRuleValidation_ExpectedFiles_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`;
    const expectedFilesPath = path.join(settings.logDir, expectedFilesFileName);

    if (!fs.existsSync(settings.logDir)) {
        fs.mkdirSync(settings.logDir, { recursive: true });
    }

    // Initialize log file
    fs.writeFileSync(logFilePath, `Bot Rule Comparison Validation Log - Run ${tempRunNumber}\n`);
    fs.appendFileSync(logFilePath, `Started at: ${new Date().toISOString()}\n`);
    fs.appendFileSync(logFilePath, `Mode: ${settings.dryRun ? 'DRY RUN (no downloads)' : 'ACTIVE (will re-download missing)'}\n`);
    fs.appendFileSync(logFilePath, `Configuration:\n`);
    fs.appendFileSync(logFilePath, `  - Processing Mode: ${processingMode}\n`);
    fs.appendFileSync(logFilePath, `  - From Date: ${settings.fromDate}\n`);
    fs.appendFileSync(logFilePath, `  - To Date: ${settings.toDate}\n`);
    fs.appendFileSync(logFilePath, `  - Comparisons to validate: ${validationList.length}\n`);
    fs.appendFileSync(logFilePath, `  - Expected files list: ${expectedFilesFileName}\n`);
    fs.appendFileSync(logFilePath, `\n`);
    
    // Initialize expected files CSV
    fs.writeFileSync(expectedFilesPath, 'Comparison,RSID,SegmentName,ReportType,FileVariant,Status,FullPath\n');

    function logToFile(message) {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] ${message}\n`;
        fs.appendFileSync(logFilePath, logEntry);
        console.log(message);
    }

    // Validation results
    const results = {
        success: true,
        comparisonsChecked: 0,
        totalFilesExpected: 0,
        filesFound: 0,
        filesMissing: 0,
        filesRedownloaded: 0,
        failedRedownloads: 0,
        errors: [],
        logFilePath,
        expectedFilesPath,
        runNumber: tempRunNumber,
        missingFileDetails: []
    };

    logToFile(`🔍 Starting validation of ${validationList.length} comparisons`);
    console.log(`📝 Log file: ${logFilePath}`);
    if (settings.dryRun) {
        console.log(`⚠️  DRY RUN MODE - Will not download missing files`);
    }

    // Setup status reporting
    let statusInterval;
    if (settings.enableStatusReporting) {
        statusInterval = setInterval(() => {
            const status = rateLimitManager.getStatus();
            if (status.queueLength > 0 || status.activeRequests > 0) {
                console.log(`📈 Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}, Downloaded: ${results.filesRedownloaded}`);
            }
        }, settings.statusReportingInterval);
    }

    try {
        // Validate each comparison
        for (let i = 0; i < validationList.length; i++) {
            const item = validationList[i];
            console.log(`\n📋 Validating ${i + 1}/${validationList.length}: ${item.cleanName} × ${item.segmentName}`);
            
            const expectedFiles = getExpectedFiles(
                baseFolder,
                settings.clientName,
                settings.fromDate,
                settings.toDate,
                item.reportToSkip,
                item.segmentId,
                item.investigationName
            );
            
            results.totalFilesExpected += expectedFiles.length;
            
            const missingFiles = [];
            for (const file of expectedFiles) {
                const fileExists = fs.existsSync(file.path);
                const status = fileExists ? 'EXISTS' : 'MISSING';
                const variant = file.hasSegment ? 'Segment' : 'AllTraffic';
                
                // Write to expected files CSV
                const csvLine = `"${item.cleanName} × ${item.segmentName}","${item.rsid}","${item.segmentName}","${file.reportType}","${variant}","${status}","${file.path}"\n`;
                fs.appendFileSync(expectedFilesPath, csvLine);
                
                if (fileExists) {
                    results.filesFound++;
                } else {
                    results.filesMissing++;
                    missingFiles.push(file);
                    results.missingFileDetails.push({
                        comparison: `${item.cleanName} × ${item.segmentName}`,
                        file: path.basename(file.path),
                        reportType: file.reportType,
                        hasSegment: file.hasSegment
                    });
                }
            }
            
            if (missingFiles.length === 0) {
                logToFile(`✅ ${item.cleanName} × ${item.segmentName}: All ${expectedFiles.length} files present`);
            } else {
                logToFile(`⚠️  ${item.cleanName} × ${item.segmentName}: ${missingFiles.length}/${expectedFiles.length} files missing`);
                
                if (!settings.dryRun) {
                    // Re-download missing files
                    for (const missingFile of missingFiles) {
                        try {
                            const suffix = missingFile.hasSegment ? 'Segment' : 'AllTraffic';
                            logToFile(`   📥 Re-downloading: ${missingFile.reportType} (${suffix})`);
                            
                            await downloadAdobeTable(
                                settings.fromDate,
                                settings.toDate,
                                missingFile.reportType,
                                settings.clientName,
                                missingFile.hasSegment ? item.segmentId : undefined,
                                item.rsid,
                                `${item.investigationName}-${suffix}`
                            );
                            
                            results.filesRedownloaded++;
                            logToFile(`   ✅ Successfully re-downloaded: ${missingFile.reportType} (${suffix})`);
                        } catch (error) {
                            results.failedRedownloads++;
                            results.success = false;
                            const errorMsg = `Failed to re-download ${missingFile.reportType}: ${error.message}`;
                            logToFile(`   ❌ ${errorMsg}`);
                            results.errors.push({
                                comparison: `${item.cleanName} × ${item.segmentName}`,
                                file: path.basename(missingFile.path),
                                error: error.message
                            });
                        }
                    }
                }
            }
            
            results.comparisonsChecked++;
        }

        // Wait for remaining requests
        if (!settings.dryRun && results.filesMissing > 0) {
            console.log("\n⏳ Waiting for remaining downloads to complete...");
            while (rateLimitManager.getStatus().activeRequests > 0 || rateLimitManager.getStatus().queueLength > 0) {
                const status = rateLimitManager.getStatus();
                console.log(`📈 Final Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}`);
                await new Promise(resolve => setTimeout(resolve, 5000));
            }
        }

        // Summary
        logToFile(`\n📊 Validation Summary:`);
        logToFile(`  - Comparisons checked: ${results.comparisonsChecked}`);
        logToFile(`  - Total files expected: ${results.totalFilesExpected}`);
        logToFile(`  - Files found: ${results.filesFound}`);
        logToFile(`  - Files missing: ${results.filesMissing}`);
        if (!settings.dryRun) {
            logToFile(`  - Files re-downloaded: ${results.filesRedownloaded}`);
            logToFile(`  - Failed re-downloads: ${results.failedRedownloads}`);
        }
        logToFile(`  - Completeness: ${((results.filesFound / results.totalFilesExpected) * 100).toFixed(2)}%`);
        logToFile(`  - Expected files list: ${expectedFilesFileName}`);

    } catch (error) {
        logToFile(`💥 An error occurred during validation: ${error.message}`);
        results.success = false;
        throw error;
    } finally {
        if (statusInterval) {
            clearInterval(statusInterval);
        }
        if (!settings.dryRun) {
            logToFile("🧹 Cleaning up rate limit manager...");
            rateLimitManager.destroy();
        }
    }

    logToFile(`Completed at: ${new Date().toISOString()}\n`);
    return results;
}

module.exports = validateBotRuleComparisons;