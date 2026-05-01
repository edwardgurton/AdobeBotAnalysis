// botInvestigationValidator.js - Validates and re-downloads missing files
const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml')
const subtractDays = require('./utils/subtractDays.js');
const retrieveValue = require('./utils/retrieveValue.js');
const downloadAdobeTable = require('./downloadAdobeTable.js');

//Get Storage Folder
let readWriteSettings;
try {
    readWriteSettings = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
    } catch (error) {
        console.error('Error loading read/write settings:', error);
        process.exit = originalExit; // Restore original exit
        return;
    }

const storageFolder = readWriteSettings.storage.folder;

// File patterns for bot investigation
const TOTALS_REPORTS = [
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

const DAILY_REPORTS = [
    'botInvestigationMetricsByDay',
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

// Initialize logging
function initializeLogging(tempDir, runIdentifier = null) {
    const tempRunNumber = runIdentifier || Math.floor(Math.random() * 1000000);
    const logFileName = `BotInvestigationValidation_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    
    if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir, { recursive: true });
    }
    
    const logFilePath = path.join(tempDir, logFileName);
    
    fs.writeFileSync(logFilePath, `Bot Investigation Validation Log - Run ${tempRunNumber}\n`);
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

// Generate expected filename based on downloadAdobeTable logic
function generateExpectedFilename(baseFolder, clientName, requestName, fileNameExtra, fromDate, toDate) {
    const folderPath = path.join(baseFolder, clientName, 'JSON');
    const fileNameExtraPart = fileNameExtra ? `_${fileNameExtra}` : '';
    return path.join(folderPath, `${clientName}_${requestName}${fileNameExtraPart}_${fromDate}_${toDate}.json`);
}

// Generate all date strings between fromDate and toDate
function generateDateRange(fromDate, toDate) {
    const dates = [];
    const start = new Date(fromDate);
    const end = new Date(toDate);
    
    for (let date = new Date(start); date <= end; date.setDate(date.getDate() + 1)) {
        dates.push(date.toISOString().split('T')[0]);
    }
    
    return dates;
}

/**
 * Get the next date string from a YYYY-MM-DD formatted date string
 * This avoids DST issues by working purely with date arithmetic
 * @param {string} dateString - Date in YYYY-MM-DD format
 * @returns {string} Next date in YYYY-MM-DD format
 */
function getNextDateString(dateString) {
    const [year, month, day] = dateString.split('-').map(Number);
    
    // Days in each month (accounting for leap years)
    const isLeapYear = (year % 4 === 0 && year % 100 !== 0) || (year % 400 === 0);
    const daysInMonth = [31, isLeapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    
    let nextDay = day + 1;
    let nextMonth = month;
    let nextYear = year;
    
    // Handle month overflow
    if (nextDay > daysInMonth[month - 1]) {
        nextDay = 1;
        nextMonth++;
        
        // Handle year overflow
        if (nextMonth > 12) {
            nextMonth = 1;
            nextYear++;
        }
    }
    
    // Format with zero padding
    const paddedMonth = nextMonth.toString().padStart(2, '0');
    const paddedDay = nextDay.toString().padStart(2, '0');
    
    return `${nextYear}-${paddedMonth}-${paddedDay}`;
}

// Check if a file exists and is valid (not empty)
function isValidFile(filePath) {
    if (!fs.existsSync(filePath)) {
        return false;
    }
    
    try {
        const stats = fs.statSync(filePath);
        return stats.size > 0;
    } catch (error) {
        return false;
    }
}

// Find files matching pattern (ignoring DIMSEG parts)
function findMatchingFiles(folderPath, pattern) {
    if (!fs.existsSync(folderPath)) {
        return [];
    }
    
    try {
        const files = fs.readdirSync(folderPath);
        // Remove DIMSEG parts from pattern for matching
        const cleanPattern = pattern.replace(/DIMSEG\d+_/g, '');
        
        return files.filter(file => {
            const cleanFile = file.replace(/DIMSEG\d+_/g, '');
            return cleanFile.includes(cleanPattern);
        });
    } catch (error) {
        return [];
    }
}

// Validate files for a single RSID
async function validateRsid(rsidCleanName, toDate, investigationRound, options, logFilePath, fromDate) {
    const { legendRsidLookup, baseFolder, clientName } = options;
    const suiteName = rsidCleanName;
    const rsid = retrieveValue(legendRsidLookup, suiteName, 'right');
    const investigationName = `${suiteName}-FullRun-V${investigationRound}`;
    
    logToFile(logFilePath, `🔍 Validating: ${suiteName} (RSID: ${rsid})`);
    
    const missingFiles = [];
    const folderPath = path.join(baseFolder, clientName, 'JSON');
    
    // Check totals reports (should have files for full date range)
    for (const reportName of TOTALS_REPORTS) {
        const fileNameExtra = `${investigationName}-Totals`
        const expectedFile = generateExpectedFilename(baseFolder, clientName, reportName, fileNameExtra, fromDate, toDate);
        console.log("ExpectedFileName;", expectedFile)
        
        if (!isValidFile(expectedFile)) {
            // Check if any files exist with this pattern (ignoring DIMSEG)
            const baseName = path.basename(expectedFile);
            const matchingFiles = findMatchingFiles(folderPath, baseName);
            
            if (matchingFiles.length === 0) {
                missingFiles.push({
                    type: 'totals',
                    reportName,
                    fromDate,
                    toDate,
                    expectedFile,
                    rsid,
                    investigationName,
                    fileNameExtra
                });
                console.log("Missing File:", expectedFile);
            }
        }
    }
    
 // Check daily reports (should have files for each date)          
const dateRange = generateDateRange(fromDate, toDate);    
for (const reportName of DAILY_REPORTS) {
    for (const date of dateRange) {
        const fileNameExtra = `${investigationName}-Daily`;
        
        // Improved date handling - work with date strings directly
        const nextDateStr = getNextDateString(date);
        
        // Debug log to verify dates
        console.log(`Current date: ${date}, Next date: ${nextDateStr}`);
        
        const expectedFile = generateExpectedFilename(baseFolder, clientName, reportName, fileNameExtra, date, nextDateStr);
        console.log("Expected File Name:", expectedFile);

        if (!isValidFile(expectedFile)) {
            // Check if any files exist with this pattern (ignoring DIMSEG)
            const baseName = path.basename(expectedFile);
            const matchingFiles = findMatchingFiles(folderPath, baseName);
            
            if (matchingFiles.length === 0) {
                missingFiles.push({
                    type: 'daily',
                    reportName,
                    fromDate: date,
                    toDate: nextDateStr,
                    expectedFile,
                    rsid,
                    investigationName,
                    fileNameExtra
                });
                console.log("Missing File:", expectedFile);
            }
        }
    }
}

    
    if (missingFiles.length > 0) {
        logToFile(logFilePath, `⚠️  Found ${missingFiles.length} missing files for ${suiteName}`);
    } else {
        logToFile(logFilePath, `✅ All files present for ${suiteName}`);
    }
    
    return {
        rsidCleanName: suiteName,
        rsid,
        missingFiles,
        isComplete: missingFiles.length === 0
    };
}

// Re-download missing files
async function redownloadMissingFiles(missingFiles, clientName, logFilePath) {
    if (missingFiles.length === 0) {
        logToFile(logFilePath, "✅ No missing files to re-download");
        return { success: true, redownloaded: 0 };
    }
    
    logToFile(logFilePath, `🔄 Re-downloading ${missingFiles.length} missing files...`);
    
    let successCount = 0;
    let failCount = 0;
    
    for (const file of missingFiles) {
        try {
            logToFile(logFilePath, `📥 Re-downloading: ${file.reportName} (${file.fromDate} to ${file.toDate})`);
            
            await downloadAdobeTable(
                file.fromDate,
                file.toDate,
                file.reportName,
                'Legend',
                undefined, // No dimSegmentID
                file.rsid,
                file.fileNameExtra
            );
            
            // Verify the file was actually downloaded
            if (isValidFile(file.expectedFile)) {
                successCount++;
                logToFile(logFilePath, `✅ Successfully re-downloaded: ${file.reportName}`);
            } else {
                failCount++;
                logToFile(logFilePath, `❌ File still missing after re-download: ${file.reportName}`);
            }
            
        } catch (error) {
            failCount++;
            logToFile(logFilePath, `❌ Failed to re-download ${file.reportName}: ${error.message}`);
        }
    }
    
    return {
        success: failCount === 0,
        redownloaded: successCount,
        failed: failCount,
        total: missingFiles.length
    };
}

// Main validation function
async function validateBotInvestigationTypeOne(investigationRound, toDate, options = {}) {
    const {
        rsidCleanNameList = require('./usefulInfo/Legend/botInvestigationMinThresholdVisits.js'),
        runIdentifier = null,
        redownloadMissing = true,
        legendRsidLookup = './usefulInfo/Legend/legendReportSuites.txt',
        baseFolder = storageFolder,
        clientName = 'Legend',
        tempDir = path.join(__dirname, 'temp'),
        // New date range options
        fromDate = null,
        daysToSubtract = 130,
        dateRangeMode = 'subtractDays' // 'subtractDays' or 'fixedFromDate'
    } = options;

    // Initialize logging
    const { logFilePath, tempRunNumber } = initializeLogging(tempDir, runIdentifier);
    
    // Calculate fromDate based on mode
    let calculatedFromDate;
    
    if (dateRangeMode === 'fixedFromDate') {
        // Mode 1: Use provided fromDate
        if (!fromDate) {
            const errorMsg = 'ERROR: fixedFromDate mode requires a fromDate parameter';
            logToFile(logFilePath, `❌ ${errorMsg}`);
            throw new Error(errorMsg);
        }
        calculatedFromDate = fromDate;
        logToFile(logFilePath, `📅 Date Range Mode: Fixed From Date`);
    } else if (dateRangeMode === 'subtractDays') {
        // Mode 2: Subtract days from toDate
        calculatedFromDate = subtractDays(toDate, daysToSubtract);
        logToFile(logFilePath, `📅 Date Range Mode: Subtract Days (${daysToSubtract} days)`);
    } else {
        const errorMsg = `ERROR: Invalid dateRangeMode: ${dateRangeMode}. Must be 'fixedFromDate' or 'subtractDays'`;
        logToFile(logFilePath, `❌ ${errorMsg}`);
        throw new Error(errorMsg);
    }
    
    logToFile(logFilePath, `🔍 Starting validation for ${rsidCleanNameList.length} RSIDs`);
    logToFile(logFilePath, `📅 Date range: ${calculatedFromDate} to ${toDate}`);
    logToFile(logFilePath, `🔢 Version: ${investigationRound}`);
    console.log(`📁 Validation log: ${logFilePath}`);
    
    const results = {
        totalRsids: rsidCleanNameList.length,
        completeRsids: 0,
        incompleteRsids: 0,
        totalMissingFiles: 0,
        redownloadResults: null,
        rsidResults: []
    };
    
    const validationOptions = {
        legendRsidLookup,
        baseFolder,
        clientName
    };
    
    try {
        // Validate each RSID
        for (let i = 0; i < rsidCleanNameList.length; i++) {
            const rsidCleanName = rsidCleanNameList[i];
            console.log(`\n📋 Validating RSID ${i + 1}/${rsidCleanNameList.length}: ${rsidCleanName}`);
            
            const rsidResult = await validateRsid(rsidCleanName, toDate, investigationRound, validationOptions, logFilePath, calculatedFromDate);
            results.rsidResults.push(rsidResult);
            
            if (rsidResult.isComplete) {
                results.completeRsids++;
            } else {
                results.incompleteRsids++;
                results.totalMissingFiles += rsidResult.missingFiles.length;
            }
        }
        
        // Summary
        logToFile(logFilePath, `\n📊 VALIDATION SUMMARY:`);
        logToFile(logFilePath, `   Complete RSIDs: ${results.completeRsids}/${results.totalRsids}`);
        logToFile(logFilePath, `   Incomplete RSIDs: ${results.incompleteRsids}/${results.totalRsids}`);
        logToFile(logFilePath, `   Total missing files: ${results.totalMissingFiles}`);
        
        // Re-download missing files if requested
        if (redownloadMissing && results.totalMissingFiles > 0) {
            logToFile(logFilePath, `\n🔄 STARTING RE-DOWNLOAD PROCESS:`);
            
            // Collect all missing files
            const allMissingFiles = results.rsidResults
                .flatMap(rsid => rsid.missingFiles);
            
            results.redownloadResults = await redownloadMissingFiles(allMissingFiles, clientName, logFilePath);
            
            logToFile(logFilePath, `\n📊 RE-DOWNLOAD SUMMARY:`);
            logToFile(logFilePath, `   Successfully re-downloaded: ${results.redownloadResults.redownloaded}`);
            logToFile(logFilePath, `   Failed to re-download: ${results.redownloadResults.failed}`);
            logToFile(logFilePath, `   Total attempted: ${results.redownloadResults.total}`);
        }
        
        logToFile(logFilePath, `\n🎉 Validation completed successfully!`);

        process.exit(0)

    } catch (error) {
        logToFile(logFilePath, `💥 Validation failed: ${error.message}`);
        throw error;
    }
}

// Export the main function
module.exports = validateBotInvestigationTypeOne;