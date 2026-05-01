// botInvestigationValidatorTypeTwo.js - Validates and re-downloads missing files for RSID/Country combinations
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
    const logFileName = `BotInvestigationValidationTypeTwo_${tempRunNumber}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    
    if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir, { recursive: true });
    }
    
    const logFilePath = path.join(tempDir, logFileName);
    
    fs.writeFileSync(logFilePath, `Bot Investigation Type Two Validation Log - Run ${tempRunNumber}\n`);
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

// Find files matching pattern (ignoring DIMSEG parts between Daily/Totals and dates)
function findMatchingFiles(folderPath, baseFileName, fileNameExtra, fromDate, toDate) {
    if (!fs.existsSync(folderPath)) {
        return [];
    }
    
    try {
        const files = fs.readdirSync(folderPath);
        
        // Extract the base pattern: everything before the fileNameExtra
        // Expected pattern: {clientName}_{reportName}_{fileNameExtra}_{fromDate}_{toDate}.json
        // Actual pattern: {clientName}_{reportName}_{fileNameExtra}_DIMSEG{segmentId}_{fromDate}_{toDate}.json
        
        // Create a pattern that matches up to Daily/Totals, then ignores DIMSEG, then matches dates
        const parts = baseFileName.split('_');
        const reportPart = parts[1]; // reportName
        const clientPart = parts[0]; // clientName
        
        return files.filter(file => {
            // Check if file matches the basic structure
            if (!file.startsWith(clientPart) || !file.includes(reportPart)) {
                return false;
            }
            
            // Check if fileNameExtra is present
            if (!file.includes(fileNameExtra)) {
                return false;
            }
            
            // Check if dates are present (ignoring anything in between)
            if (!file.includes(fromDate) || !file.includes(toDate)) {
                return false;
            }
            
            // Verify the dates appear in the correct order near the end
            const datePattern = `${fromDate}_${toDate}.json`;
            if (!file.endsWith(datePattern)) {
                return false;
            }
            
            return true;
        });
    } catch (error) {
        return [];
    }
}

// Validate files for a single RSID/Country combination
async function validateRsidCountry(rsidCountryData, toDate, investigationRound, options, logFilePath) {
    const { legendRsidLookup, baseFolder, clientName, subtractDaysValue } = options;
    const { rsidCleanName, geocountry, segmentId, visits } = rsidCountryData;
    const suiteName = rsidCleanName;
    const fromDate = subtractDays(toDate, subtractDaysValue);
    const rsid = retrieveValue(legendRsidLookup, suiteName, 'right');
    const investigationName = `${suiteName}-${geocountry}-FullRun-V${investigationRound}`;
    
    logToFile(logFilePath, `🔍 Validating: ${suiteName} - ${geocountry} (RSID: ${rsid}, Segment: ${segmentId}, Visits: ${visits.toLocaleString()})`);
    
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
            const matchingFiles = findMatchingFiles(folderPath, baseName, fileNameExtra, fromDate, toDate);
            
            if (matchingFiles.length === 0) {
                missingFiles.push({
                    type: 'totals',
                    reportName,
                    fromDate,
                    toDate,
                    expectedFile,
                    rsid,
                    segmentId,
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
                const matchingFiles = findMatchingFiles(folderPath, baseName, fileNameExtra, date, nextDateStr);
                
                if (matchingFiles.length === 0) {
                    missingFiles.push({
                        type: 'daily',
                        reportName,
                        fromDate: date,
                        toDate: nextDateStr,
                        expectedFile,
                        rsid,
                        segmentId,
                        investigationName,
                        fileNameExtra
                    });
                    console.log("Missing File:", expectedFile);
                }
            }
        }
    }
    
    if (missingFiles.length > 0) {
        logToFile(logFilePath, `⚠️  Found ${missingFiles.length} missing files for ${suiteName} - ${geocountry}`);
    } else {
        logToFile(logFilePath, `✅ All files present for ${suiteName} - ${geocountry}`);
    }
    
    return {
        rsidCleanName: suiteName,
        geocountry,
        rsid,
        segmentId,
        visits,
        missingFiles,
        isComplete: missingFiles.length === 0
    };
}

// Re-download missing files
async function redownloadMissingFiles(missingFiles, clientName, baseFolder, logFilePath) {
    if (missingFiles.length === 0) {
        logToFile(logFilePath, "✅ No missing files to re-download");
        return { success: true, redownloaded: 0 };
    }
    
    logToFile(logFilePath, `🔄 Re-downloading ${missingFiles.length} missing files...`);
    
    let successCount = 0;
    let failCount = 0;
    
    const folderPath = path.join(baseFolder, clientName, 'JSON');
    
    for (const file of missingFiles) {
        try {
            logToFile(logFilePath, `📥 Re-downloading: ${file.reportName} (${file.fromDate} to ${file.toDate})`);
            
            await downloadAdobeTable(
                file.fromDate,
                file.toDate,
                file.reportName,
                'Legend',
                file.segmentId,
                file.rsid,
                file.fileNameExtra
            );
            
            // Verify the file was actually downloaded (ignoring DIMSEG in filename)
            const baseName = path.basename(file.expectedFile);
            const matchingFiles = findMatchingFiles(folderPath, baseName, file.fileNameExtra, file.fromDate, file.toDate);
            
            if (matchingFiles.length > 0) {
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
async function validateBotInvestigationTypeTwo(investigationRound, toDate, options = {}) {
    const {
        rsidCountriesList = require('./usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js'),
        rsidCleanNames = null,
        countries = null,
        subtractDaysValue = 130,
        runIdentifier = null,
        redownloadMissing = true,
        legendRsidLookup = './usefulInfo/Legend/legendReportSuites.txt',
        baseFolder = storageFolder,
        clientName = 'Legend',
        tempDir = path.join(__dirname, 'temp')
    } = options;

    // Apply filters if specified
    let filteredList = rsidCountriesList;
    const originalCount = rsidCountriesList.length;
    
    if (rsidCleanNames && Array.isArray(rsidCleanNames) && rsidCleanNames.length > 0) {
        filteredList = filteredList.filter(item => rsidCleanNames.includes(item.rsidCleanName));
    }
    if (countries && Array.isArray(countries) && countries.length > 0) {
        filteredList = filteredList.filter(item => countries.includes(item.geocountry));
    }
    
    if (filteredList.length === 0) {
        throw new Error('No RSID/Country combinations match the specified filters');
    }

    // Initialize logging
    const { logFilePath, tempRunNumber } = initializeLogging(tempDir, runIdentifier);
    
    logToFile(logFilePath, `🔍 Starting validation for ${filteredList.length} RSID/Country combinations`);
    if (originalCount !== filteredList.length) {
        logToFile(logFilePath, `   (Filtered from ${originalCount} total combinations)`);
        if (rsidCleanNames && rsidCleanNames.length > 0) {
            logToFile(logFilePath, `   - Filtered by RSID Clean Names: ${rsidCleanNames.join(', ')}`);
        }
        if (countries && countries.length > 0) {
            logToFile(logFilePath, `   - Filtered by Countries: ${countries.join(', ')}`);
        }
    }
    logToFile(logFilePath, `📅 Date range: ${subtractDays(toDate, subtractDaysValue)} to ${toDate}`);
    logToFile(logFilePath, `🔢 Version: ${investigationRound}`);
    console.log(`📝 Validation log: ${logFilePath}`);
    
    const results = {
        totalCombinations: filteredList.length,
        completeCombinations: 0,
        incompleteCombinations: 0,
        totalMissingFiles: 0,
        redownloadResults: null,
        combinationResults: []
    };
    
    const validationOptions = {
        legendRsidLookup,
        baseFolder,
        clientName,
        subtractDaysValue
    };
    
    try {
        // Validate each RSID/Country combination
        for (let i = 0; i < filteredList.length; i++) {
            const rsidCountryData = filteredList[i];
            console.log(`\n📋 Validating combination ${i + 1}/${filteredList.length}: ${rsidCountryData.rsidCleanName} - ${rsidCountryData.geocountry}`);
            
            const combinationResult = await validateRsidCountry(rsidCountryData, toDate, investigationRound, validationOptions, logFilePath);
            results.combinationResults.push(combinationResult);
            
            if (combinationResult.isComplete) {
                results.completeCombinations++;
            } else {
                results.incompleteCombinations++;
                results.totalMissingFiles += combinationResult.missingFiles.length;
            }
        }
        
        // Summary
        logToFile(logFilePath, `\n📊 VALIDATION SUMMARY:`);
        logToFile(logFilePath, `   Complete RSID/Country combinations: ${results.completeCombinations}/${results.totalCombinations}`);
        logToFile(logFilePath, `   Incomplete RSID/Country combinations: ${results.incompleteCombinations}/${results.totalCombinations}`);
        logToFile(logFilePath, `   Total missing files: ${results.totalMissingFiles}`);
        
        // Re-download missing files if requested
        if (redownloadMissing && results.totalMissingFiles > 0) {
            logToFile(logFilePath, `\n🔄 STARTING RE-DOWNLOAD PROCESS:`);
            
            // Collect all missing files
            const allMissingFiles = results.combinationResults
                .flatMap(combination => combination.missingFiles);
            
            results.redownloadResults = await redownloadMissingFiles(allMissingFiles, clientName, baseFolder, logFilePath);
            
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
module.exports = validateBotInvestigationTypeTwo;

// Execute when run directly
if (require.main === module) {
    // Configuration - modify these values as needed
    const investigationRound = 4.0;
    const toDate = '2025-05-31';
    const options = {
        // Optional: specify number of days to subtract from toDate (default is 130)
        // subtractDaysValue: 90,
        
        // Optional: filter by specific RSIDs
        // rsidCleanNames: ['Apuestasdeportivascom', 'Casinoguru'],
        
        // Optional: filter by specific countries
        // countries: ['Spain', 'Peru'],
        
        // Optional: disable re-downloading missing files
        // redownloadMissing: false,
    };

    // Run the validator
    validateBotInvestigationTypeTwo(investigationRound, toDate, options)
        .then(result => {
            console.log('\n✨ Validation complete!');
            process.exit(0);
        })
        .catch(error => {
            console.error('💥 Fatal error:', error);
            process.exit(1);
        });
}