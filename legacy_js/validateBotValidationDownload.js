// validateBotValidationDownload.js - Optimized version with shared report handling
const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { downloadBotRuleValidationData, copySharedReportsForBotRule, SHARED_REPORTS, BOT_SPECIFIC_REPORTS } = require('./downloadBotRuleValidationData.js');

// Get Storage Folder
let readWriteSettings;
try {
    readWriteSettings = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
} catch (error) {
    console.error('Error loading read/write settings:', error);
    process.exit(1);
}

const storageFolder = readWriteSettings.storage.folder;

// All bot validation reports (including shared ones)
const BOT_VALIDATION_REPORTS = [...SHARED_REPORTS, ...BOT_SPECIFIC_REPORTS];

// Initialize logging
function initializeLogging(tempDir, runIdentifier = null) {
    const tempRunNumber = runIdentifier || Math.floor(Math.random() * 1000000);
    const logFileName = `BotValidationValidation_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    
    if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir, { recursive: true });
    }
    
    const logFilePath = path.join(tempDir, logFileName);
    
    fs.writeFileSync(logFilePath, `Bot Validation Download Validation Log - Run ${tempRunNumber}\n`);
    fs.appendFileSync(logFilePath, `Started at: ${new Date().toISOString()}\n\n`);
    
    return { logFilePath, tempRunNumber };
}

// Logging function
function logToFile(logFilePath, message) {
    const timestamp = new Date().toISOString();
    const logEntry = `[${timestamp}] ${message}\n`;
    
    if (logFilePath) {
        fs.appendFileSync(logFilePath, logEntry);
    }
    console.log(message);
}

// Generate expected filename based on bot validation naming pattern
function generateExpectedFilename(baseFolder, clientName, requestName, botRuleName, rsidCleanName, fromDate, toDate) {
    const folderPath = path.join(baseFolder, clientName, 'JSON');
    return path.join(folderPath, `${clientName}_${requestName}_${botRuleName}_${rsidCleanName}_*${fromDate}_${toDate}.json`);
}

// Check if a file exists and is valid (not empty) - handles wildcard patterns
function isValidFile(filePattern) {
    const folderPath = path.dirname(filePattern);
    const fileName = path.basename(filePattern);
    
    if (!fs.existsSync(folderPath)) {
        return false;
    }
    
    try {
        const files = fs.readdirSync(folderPath);
        const regex = new RegExp(fileName.replace(/\*/g, '.*'));
        
        const matchingFiles = files.filter(file => regex.test(file));
        
        if (matchingFiles.length === 0) {
            return false;
        }
        
        // Check if at least one matching file has content
        for (const file of matchingFiles) {
            const fullPath = path.join(folderPath, file);
            const stats = fs.statSync(fullPath);
            if (stats.size > 0) {
                return true;
            }
        }
        
        return false;
    } catch (error) {
        return false;
    }
}

/**
 * Check if shared report exists (with "SHARED" in the name)
 */
function checkSharedReportExists(baseFolder, clientName, reportName, rsidCleanName, fromDate, toDate) {
    const sharedPattern = generateExpectedFilename(
        baseFolder, 
        clientName, 
        reportName, 
        'SHARED', 
        rsidCleanName, 
        fromDate, 
        toDate
    );
    return isValidFile(sharedPattern);
}

/**
 * Validates files for a single bot rule across all RSIDs
 */
async function validateBotRule(fromDate, toDate, botRuleName, dimSegmentId, options, logFilePath) {
    const { rsidCleanNameList, baseFolder, clientName } = options;
    
    logToFile(logFilePath, `🔍 Validating bot rule: ${botRuleName}`);
    logToFile(logFilePath, `📅 Date range: ${fromDate} to ${toDate}`);
    
    const missingFiles = [];
    const missingSharedReports = []; // Track separately
    
    // Check each RSID for all expected reports
    for (const rsidCleanName of rsidCleanNameList) {
        for (const reportName of BOT_VALIDATION_REPORTS) {
            const expectedFilePattern = generateExpectedFilename(
                baseFolder, 
                clientName, 
                reportName, 
                botRuleName, 
                rsidCleanName, 
                fromDate, 
                toDate
            );
            
            console.log(`Checking: ${expectedFilePattern}`);
            
            const fileExists = isValidFile(expectedFilePattern);
            
            if (!fileExists) {
                // Check if this is a shared report
                const isSharedReport = SHARED_REPORTS.includes(reportName);
                
                if (isSharedReport) {
                    // Check if the shared version exists
                    const sharedExists = checkSharedReportExists(
                        baseFolder, clientName, reportName, rsidCleanName, fromDate, toDate
                    );
                    
                    if (sharedExists) {
                        // Shared report exists, we just need to copy it
                        missingSharedReports.push({
                            reportName,
                            botRuleName,
                            rsidCleanName,
                            fromDate,
                            toDate,
                            expectedPattern: expectedFilePattern,
                            needsCopy: true // Flag to indicate we should copy, not re-download
                        });
                        console.log(`Shared report exists, needs copy: ${expectedFilePattern}`);
                    } else {
                        // Neither bot-specific nor shared version exists
                        missingFiles.push({
                            reportName,
                            botRuleName,
                            rsidCleanName,
                            fromDate,
                            toDate,
                            expectedPattern: expectedFilePattern,
                            dimSegmentId,
                            isShared: true
                        });
                        console.log(`Missing shared report: ${expectedFilePattern}`);
                    }
                } else {
                    // Bot-specific report is missing
                    missingFiles.push({
                        reportName,
                        botRuleName,
                        rsidCleanName,
                        fromDate,
                        toDate,
                        expectedPattern: expectedFilePattern,
                        dimSegmentId,
                        isShared: false
                    });
                    console.log(`Missing file pattern: ${expectedFilePattern}`);
                }
            }
        }
    }
    
    const totalMissing = missingFiles.length + missingSharedReports.length;
    
    if (totalMissing > 0) {
        logToFile(logFilePath, `⚠️  Found ${missingFiles.length} missing files + ${missingSharedReports.length} files needing copy for bot rule: ${botRuleName}`);
    } else {
        logToFile(logFilePath, `✅ All files present for bot rule: ${botRuleName}`);
    }
    
    return {
        botRuleName,
        dimSegmentId,
        missingFiles,
        missingSharedReports,
        isComplete: totalMissing === 0
    };
}

/**
 * Re-downloads missing files or copies shared reports as needed
 */
async function redownloadMissingFiles(missingFiles, missingSharedReports, fromDate, toDate, clientName, legendRsidList, logFilePath) {
    const totalMissing = missingFiles.length + missingSharedReports.length;
    
    if (totalMissing === 0) {
        logToFile(logFilePath, "✅ No missing files to re-download or copy");
        return { success: true, redownloaded: 0, copied: 0 };
    }
    
    const downloadAdobeTable = require('./downloadAdobeTable.js');
    const retrieveValue = require('./utils/retrieveValue.js');
    const legendRsidLookup = './usefulInfo/Legend/legendReportSuites.txt';
    
    logToFile(logFilePath, `🔄 Processing ${missingFiles.length} files to re-download and ${missingSharedReports.length} files to copy...`);
    
    let downloadSuccessCount = 0;
    let downloadFailCount = 0;
    let copySuccessCount = 0;
    let copyFailCount = 0;
    
    // First, handle files that need copying from shared reports
    if (missingSharedReports.length > 0) {
        logToFile(logFilePath, `\n📋 Copying ${missingSharedReports.length} shared reports...`);
        
        // Group by bot rule to copy efficiently
        const byBotRule = {};
        missingSharedReports.forEach(file => {
            if (!byBotRule[file.botRuleName]) {
                byBotRule[file.botRuleName] = [];
            }
            byBotRule[file.botRuleName].push(file);
        });
        
        for (const [botRuleName, files] of Object.entries(byBotRule)) {
            try {
                logToFile(logFilePath, `📋 Copying shared reports for: ${botRuleName}`);
                await copySharedReportsForBotRule(
                    legendRsidList,
                    fromDate,
                    toDate,
                    clientName,
                    botRuleName
                );
                
                // Verify copies
                for (const file of files) {
                    if (isValidFile(file.expectedPattern)) {
                        copySuccessCount++;
                        logToFile(logFilePath, `✅ Successfully copied: ${file.reportName} for ${file.rsidCleanName}`);
                    } else {
                        copyFailCount++;
                        logToFile(logFilePath, `❌ Copy failed: ${file.reportName} for ${file.rsidCleanName}`);
                    }
                }
            } catch (error) {
                copyFailCount += files.length;
                logToFile(logFilePath, `❌ Failed to copy shared reports for ${botRuleName}: ${error.message}`);
            }
        }
    }
    
    // Then, handle files that need re-downloading
    if (missingFiles.length > 0) {
        logToFile(logFilePath, `\n📥 Re-downloading ${missingFiles.length} missing files...`);
        
        for (const file of missingFiles) {
            try {
                const rsid = retrieveValue(legendRsidLookup, file.rsidCleanName, 'right');
                const fileNameExtra = file.botRuleName + '_' + file.rsidCleanName;
                
                // For shared reports, use "SHARED" as the botRuleName in the download
                const downloadBotRuleName = file.isShared ? 'SHARED' : file.botRuleName;
                const downloadFileNameExtra = file.isShared ? 'SHARED_' + file.rsidCleanName : fileNameExtra;
                
                // Determine if this report type should use dimSegmentId
                const shouldUseDimSegmentId = BOT_SPECIFIC_REPORTS.includes(file.reportName);
                const dimSegmentIdToPass = shouldUseDimSegmentId ? file.dimSegmentId : undefined;
                
                logToFile(logFilePath, `📥 Re-downloading: ${file.reportName} for ${file.rsidCleanName} (${downloadBotRuleName})`);
                logToFile(logFilePath, `   Using dimSegmentId: ${dimSegmentIdToPass ? 'YES' : 'NO'}`);
                
                await downloadAdobeTable(
                    file.fromDate,
                    file.toDate,
                    file.reportName,
                    clientName,
                    dimSegmentIdToPass,
                    rsid,
                    downloadFileNameExtra
                );
                
                // Verify the download
                const checkPattern = file.isShared ? 
                    generateExpectedFilename(storageFolder, clientName, file.reportName, 'SHARED', file.rsidCleanName, file.fromDate, file.toDate) :
                    file.expectedPattern;
                
                if (isValidFile(checkPattern)) {
                    downloadSuccessCount++;
                    logToFile(logFilePath, `✅ Successfully re-downloaded: ${file.reportName} for ${file.rsidCleanName}`);
                    
                    // If this was a shared report, now copy it to the bot rule name
                    if (file.isShared) {
                        try {
                            await copySharedReportsForBotRule(
                                legendRsidList,
                                file.fromDate,
                                file.toDate,
                                clientName,
                                file.botRuleName
                            );
                            if (isValidFile(file.expectedPattern)) {
                                logToFile(logFilePath, `✅ Copied to bot rule: ${file.botRuleName}`);
                            }
                        } catch (copyError) {
                            logToFile(logFilePath, `⚠️  Downloaded but copy failed: ${copyError.message}`);
                        }
                    }
                } else {
                    downloadFailCount++;
                    logToFile(logFilePath, `❌ File still missing after re-download: ${file.reportName} for ${file.rsidCleanName}`);
                }
                
            } catch (error) {
                downloadFailCount++;
                logToFile(logFilePath, `❌ Failed to re-download ${file.reportName} for ${file.rsidCleanName}: ${error.message}`);
            }
        }
    }
    
    return {
        success: (downloadFailCount + copyFailCount) === 0,
        redownloaded: downloadSuccessCount,
        copied: copySuccessCount,
        downloadFailed: downloadFailCount,
        copyFailed: copyFailCount,
        total: totalMissing
    };
}

/**
 * Validates bot validation files for a single bot rule and optionally re-downloads missing files
 */
async function validateBotValidationDownload(fromDate, toDate, botRuleName, dimSegmentId, options = {}) {
    const {
        rsidCleanNameList = require('./usefulInfo/Legend/botValidationRsidList.js'),
        runIdentifier = null,
        redownloadMissing = true,
        baseFolder = storageFolder,
        clientName = 'Legend',
        tempDir = path.join(__dirname, 'temp'),
        exitOnCompletion = true
    } = options;

    const { logFilePath, tempRunNumber } = initializeLogging(tempDir, runIdentifier);
    
    logToFile(logFilePath, `🔍 Starting validation for bot rule: ${botRuleName}`);
    logToFile(logFilePath, `📅 Date range: ${fromDate} to ${toDate}`);
    logToFile(logFilePath, `🏢 Validating across ${rsidCleanNameList.length} RSIDs`);
    console.log(`📝 Validation log: ${logFilePath}`);
    
    const validationOptions = {
        rsidCleanNameList,
        baseFolder,
        clientName
    };
    
    try {
        const botRuleResult = await validateBotRule(fromDate, toDate, botRuleName, dimSegmentId, validationOptions, logFilePath);
        
        const results = {
            botRuleName,
            dimSegmentId,
            totalExpectedFiles: rsidCleanNameList.length * BOT_VALIDATION_REPORTS.length,
            missingFiles: botRuleResult.missingFiles.length,
            missingSharedReports: botRuleResult.missingSharedReports.length,
            isComplete: botRuleResult.isComplete,
            redownloadResults: null
        };
        
        logToFile(logFilePath, `\n📊 VALIDATION SUMMARY:`);
        logToFile(logFilePath, `   Bot rule: ${botRuleName}`);
        logToFile(logFilePath, `   Expected files: ${results.totalExpectedFiles}`);
        logToFile(logFilePath, `   Missing files: ${results.missingFiles}`);
        logToFile(logFilePath, `   Files needing copy: ${results.missingSharedReports}`);
        logToFile(logFilePath, `   Complete: ${results.isComplete ? 'YES' : 'NO'}`);
        
        if (redownloadMissing && (results.missingFiles > 0 || results.missingSharedReports > 0)) {
            logToFile(logFilePath, `\n🔄 STARTING RECOVERY PROCESS:`);
            
            results.redownloadResults = await redownloadMissingFiles(
                botRuleResult.missingFiles,
                botRuleResult.missingSharedReports,
                fromDate,
                toDate,
                clientName,
                rsidCleanNameList,
                logFilePath
            );
            
            logToFile(logFilePath, `\n📊 RECOVERY SUMMARY:`);
            logToFile(logFilePath, `   Successfully re-downloaded: ${results.redownloadResults.redownloaded}`);
            logToFile(logFilePath, `   Successfully copied: ${results.redownloadResults.copied}`);
            logToFile(logFilePath, `   Failed to download: ${results.redownloadResults.downloadFailed}`);
            logToFile(logFilePath, `   Failed to copy: ${results.redownloadResults.copyFailed}`);
            logToFile(logFilePath, `   Total processed: ${results.redownloadResults.total}`);
        }
        
        logToFile(logFilePath, `\n🎉 Validation completed successfully!`);
        
        if (exitOnCompletion) {
            process.exit(0);
        }
        
        return results;

    } catch (error) {
        logToFile(logFilePath, `💥 Validation failed: ${error.message}`);
        
        if (exitOnCompletion) {
            process.exit(1);
        }
        
        throw error;
    }
}

/**
 * Validates bot validation files for multiple bot rules in batch
 */
async function validateMultipleBotRules(fromDate, toDate, botRulesList, options = {}) {
    const {
        runIdentifier = null,
        redownloadMissing = true,
        tempDir = path.join(__dirname, 'temp')
    } = options;

    const { logFilePath, tempRunNumber } = initializeLogging(tempDir, runIdentifier);
    
    logToFile(logFilePath, `🔍 Starting batch validation for ${botRulesList.length} bot rules`);
    logToFile(logFilePath, `📅 Date range: ${fromDate} to ${toDate}`);
    console.log(`📝 Batch validation log: ${logFilePath}`);
    
    const batchResults = {
        totalBotRules: botRulesList.length,
        completeBotRules: 0,
        incompleteBotRules: 0,
        totalMissingFiles: 0,
        botRuleResults: []
    };
    
    try {
        for (let i = 0; i < botRulesList.length; i++) {
            const botRule = botRulesList[i];
            logToFile(logFilePath, `\n📋 Validating bot rule ${i + 1}/${botRulesList.length}: ${botRule.botRuleName}`);
            
            const validationOptions = {
                rsidCleanNameList: options.rsidCleanNameList || require('./usefulInfo/Legend/botValidationRsidList.js'),
                baseFolder: options.baseFolder || storageFolder,
                clientName: options.clientName || 'Legend'
            };
            
            const botRuleResult = await validateBotRule(
                fromDate,
                toDate,
                botRule.botRuleName,
                botRule.dimSegmentId,
                validationOptions,
                logFilePath
            );
            
            const result = {
                botRuleName: botRule.botRuleName,
                dimSegmentId: botRule.dimSegmentId,
                totalExpectedFiles: validationOptions.rsidCleanNameList.length * BOT_VALIDATION_REPORTS.length,
                missingFiles: botRuleResult.missingFiles.length,
                missingSharedReports: botRuleResult.missingSharedReports.length,
                isComplete: botRuleResult.isComplete,
                redownloadResults: null
            };
            
            if (redownloadMissing && (result.missingFiles > 0 || result.missingSharedReports > 0)) {
                logToFile(logFilePath, `🔄 Recovering missing files for ${botRule.botRuleName}...`);
                
                result.redownloadResults = await redownloadMissingFiles(
                    botRuleResult.missingFiles,
                    botRuleResult.missingSharedReports,
                    fromDate,
                    toDate,
                    validationOptions.clientName,
                    validationOptions.rsidCleanNameList,
                    logFilePath
                );
                
                logToFile(logFilePath, `📊 Recovery results for ${botRule.botRuleName}: ${result.redownloadResults.redownloaded} downloaded, ${result.redownloadResults.copied} copied`);
            }
            
            batchResults.botRuleResults.push(result);
            
            if (result.isComplete) {
                batchResults.completeBotRules++;
            } else {
                batchResults.incompleteBotRules++;
                batchResults.totalMissingFiles += (result.missingFiles + result.missingSharedReports);
            }
        }
        
        logToFile(logFilePath, `\n📊 BATCH VALIDATION SUMMARY:`);
        logToFile(logFilePath, `   Complete bot rules: ${batchResults.completeBotRules}/${batchResults.totalBotRules}`);
        logToFile(logFilePath, `   Incomplete bot rules: ${batchResults.incompleteBotRules}/${batchResults.totalBotRules}`);
        logToFile(logFilePath, `   Total missing files: ${batchResults.totalMissingFiles}`);
        
        logToFile(logFilePath, `\n🎉 Batch validation completed successfully!`);
        
        process.exit(0);

    } catch (error) {
        logToFile(logFilePath, `💥 Batch validation failed: ${error.message}`);
        process.exit(1);
    }
}

module.exports = {
    validateBotValidationDownload,
    validateMultipleBotRules
};

if (require.main === module) {
    const botRulesList = [
        {
            "dimSegmentId": "s3938_68875fcb762ef06cc5283857",
            "botRuleName": "0099SBR-SG-UserAgent"
        }
    ];
    
    validateMultipleBotRules('2023-08-01', '2025-08-01', botRulesList)
        .catch(console.error);
}