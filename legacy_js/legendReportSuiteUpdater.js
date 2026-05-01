const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const getMultipleReportSuites = require('./utils/getMultipleReportSuites');
const GenerateLegendReportSuiteLists = require('./utils/GenerateLegendReportSuiteLists');
const iterateRsidRequests = require('./utils/iterateRsidRequests');
const processJSONFilesSummaryTotalOnly = require('./processJSONFilesSummaryTotalOnly');
const concatenateCSVs = require('./utils/concatenateCSVs');
const rateLimitManager = require('./utils/RateLimitManager');
const excludedRsidCleanNames = require('./usefulInfo/Legend/excludedRsidCleanNames');

/**
 * LegendReportSuiteUpdater - Downloads and processes Adobe Analytics report suites
 * @param {boolean} includeVirtualReportSuites - Include virtual report suites (prefix: vrs_)
 * @param {number} minimumVisitsInvestigation - Minimum visits for investigation
 * @param {number} minimumVisitsValidation - Minimum visits for validation
 * @param {string} fromDate - Optional start date in 'YYYY-MM-DD' format. If not provided, uses 90 days before toDate or yesterday
 * @param {string} toDate - Optional end date in 'YYYY-MM-DD' format. If not provided, uses yesterday's date
 */
async function LegendReportSuiteUpdater(
    includeVirtualReportSuites = true,
    minimumVisitsInvestigation = 3000,
    minimumVisitsValidation = 3000,
    fromDate = null,
    toDate = null
) {
    console.log('Starting LegendReportSuiteUpdater...');
    console.log(`Configuration:
    - Include Virtual Report Suites: ${includeVirtualReportSuites}
    - Minimum Visits for Investigation: ${minimumVisitsInvestigation}
    - Minimum Visits for Validation: ${minimumVisitsValidation}
    - Custom To Date: ${toDate || 'Not specified (will use yesterday)'}
    - Custom From Date: ${fromDate || 'Not specified (will use 90 days before toDate/yesterday)'}`);

    // Prevent unexpected process exits
    const originalExit = process.exit;
    let exitPrevented = false;
    
    process.exit = function(code) {
        if (!exitPrevented) {
            console.log(`⚠️  Process.exit(${code}) was called but prevented. Continuing execution...`);
            console.log('Stack trace:', new Error().stack);
            exitPrevented = true;
            return;
        }
        originalExit.call(this, code);
    };

    try {
        // Step 1: Generate runName with UNIX timestamp
        const runName = `TEMP${Math.floor(Date.now() / 1000)}`;
        console.log(`Generated runName: ${runName}`);

        // Step 2: Call getMultipleReportSuites
        console.log('Step 2: Downloading report suites...');
        const fileName = `LegendReportSuites${runName}`;
        await getMultipleReportSuites('Legend', fileName);
        console.log('Report suites downloaded successfully');

        // Wait a moment to ensure file is written
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Step 3: Generate report suite lists using the utility function
        console.log('Step 3: Generating report suite lists...');
        
        // Read storage folder from settings
        let readWriteSettings;
        try {
            readWriteSettings = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
        } catch (error) {
            console.error('Error loading read/write settings:', error);
            process.exit = originalExit; // Restore original exit
            return;
        }

        const storageFolder = readWriteSettings.storage.folder;
        const jsonFilePath = path.join(storageFolder, 'savedOutputs', `${fileName}.json`);
        
        await GenerateLegendReportSuiteLists(jsonFilePath);
        console.log('Report suite lists generated successfully');

        // Step 4: Create RSID clean names array from downloaded file
        console.log('Step 4: Processing RSID clean names...');
        let reportSuitesData;
        try {
            const fileContent = fs.readFileSync(jsonFilePath, 'utf8');
            reportSuitesData = JSON.parse(fileContent);
        } catch (error) {
            console.error('Error reading report suites file:', error);
            process.exit = originalExit; // Restore original exit
            return;
        }

        // Filter report suites first, then extract clean names
        let filteredSuites = reportSuitesData.content;

        if (!includeVirtualReportSuites) {
            const originalCount = filteredSuites.length;
            filteredSuites = filteredSuites.filter(suite => !suite.rsid.startsWith('vrs_'));
            console.log(`Filtered out ${originalCount - filteredSuites.length} virtual report suites`);
        }

        // Generate clean names for the filtered suites
        let rsidCleanNamesList = filteredSuites.map(suite => {
            let cleanName = suite.name
                .replace(/\s+/g, '') // Remove all spaces
                .replace(/\./g, '') // Remove all full stops
                .replace(/\s*-\s*Production/gi, ''); // Remove " - Production" (case insensitive)
            
            return cleanName;
        });

        console.log(`Total RSID clean names to process: ${rsidCleanNamesList.length}`);

        
        // Step 5: Call iterateRsidRequests with improved error handling
        console.log('Step 5: Starting RSID requests...');
        
        // Calculate date range based on provided parameters
        let fromDateObj, toDateObj, fromDateStr, toDateStr, todayStr;
        
        // Validate fromDate if provided
        if (fromDate) {
            const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
            if (!dateRegex.test(fromDate)) {
                throw new Error(`Invalid date format for fromDate: ${fromDate}. Expected format: YYYY-MM-DD`);
            }
            
            fromDateObj = new Date(fromDate);
            if (isNaN(fromDateObj.getTime())) {
                throw new Error(`Invalid date value for fromDate: ${fromDate}`);
            }
        }
        
        // Validate toDate if provided
        if (toDate) {
            const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
            if (!dateRegex.test(toDate)) {
                throw new Error(`Invalid date format for toDate: ${toDate}. Expected format: YYYY-MM-DD`);
            }
            
            toDateObj = new Date(toDate);
            if (isNaN(toDateObj.getTime())) {
                throw new Error(`Invalid date value for toDate: ${toDate}`);
            }
        }
        
        // Calculate final date range
        if (fromDate && toDate) {
            // Both dates provided - use as is
            fromDateStr = fromDate;
            toDateStr = toDate;
        } else if (fromDate && !toDate) {
            // Only fromDate provided - use yesterday as toDate
            const today = new Date();
            toDateObj = new Date(today);
            toDateObj.setDate(today.getDate() - 1);
            toDateStr = toDateObj.toISOString().split('T')[0];
            fromDateStr = fromDate;
        } else if (!fromDate && toDate) {
            // Only toDate provided - calculate fromDate as 90 days before toDate
            fromDateObj = new Date(toDate);
            fromDateObj.setDate(fromDateObj.getDate() - 90);
            fromDateStr = fromDateObj.toISOString().split('T')[0];
            toDateStr = toDate;
        } else {
            // Neither date provided - use original logic (yesterday - 90 days to yesterday)
            const today = new Date();
            fromDateObj = new Date(today);
            fromDateObj.setDate(today.getDate() - 90);
            toDateObj = new Date(today);
            toDateObj.setDate(today.getDate() - 1);
            fromDateStr = fromDateObj.toISOString().split('T')[0];
            toDateStr = toDateObj.toISOString().split('T')[0];
        }
        
        // Get today string for logging in output file
        const today = new Date();
        todayStr = today.toISOString().split('T')[0];

        console.log(`Date range: ${fromDateStr} to ${toDateStr}`);

        // Monitor rate limit manager status during execution
        const statusMonitor = setInterval(() => {
            const status = rateLimitManager.getStatus();
            if (status.queueLength > 0 || status.activeRequests > 0 || status.isPaused) {
                console.log(`📊 Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}, Paused: ${status.isPaused ? 'YES until ' + status.pauseUntil : 'NO'}`);
            }
        }, 15000); // Every 15 seconds

        // Execute the RSID requests - let RateLimitManager handle all 429 errors
        try {
            console.log('🚀 Starting iterateRsidRequests...');
            await iterateRsidRequests(
                rsidCleanNamesList,
                fromDateStr,
                toDateStr,
                'toplineMetricsForRsidValidation',
                'Legend',
                undefined, // No dimSegmentId
                runName
            );
            console.log('✅ RSID requests completed successfully');
        } catch (error) {
            // Log the error but continue with whatever data we have
            console.log(`⚠️  RSID requests completed with some errors: ${error.message}`);
            console.log('📊 Continuing with available data...');
        } finally {
            clearInterval(statusMonitor);
        }

        // Wait for any remaining requests to complete
        console.log('⏳ Waiting for any remaining requests to complete...');
        let waitCount = 0;
        while (rateLimitManager.getStatus().activeRequests > 0 || rateLimitManager.getStatus().queueLength > 0) {
            const status = rateLimitManager.getStatus();
            console.log(`📈 Waiting - Queue: ${status.queueLength}, Active: ${status.activeRequests}`);
            await new Promise(resolve => setTimeout(resolve, 2000));
            waitCount++;
            if (waitCount > 30) { // Max 60 seconds wait
                console.log('⏰ Max wait time reached, continuing with available data...');
                break;
            }
        }

        // Step 5.5: Validate downloads and retry missing files
        console.log('Step 5.5: Validating downloads and retrying missing files...');

        const validateAndRetryMissingDownloads = require('./utils/LGRSUValidateAndRetryMissingDownloads');

        try {
            const validationResults = await validateAndRetryMissingDownloads(
                rsidCleanNamesList,
                fromDateStr,
                toDateStr,
                runName,
                storageFolder
            );
            
            console.log(`✅ Download validation completed - ${validationResults.foundFiles.length}/${validationResults.totalExpected} files found`);
            
            // Optional: Warning for low success rates
            const successRate = (validationResults.foundFiles.length / validationResults.totalExpected) * 100;
            if (successRate < 80) {
                console.log(`⚠️  Warning: Low success rate (${successRate.toFixed(1)}%). Consider investigating network issues.`);
            }
            
        } catch (error) {
            console.log(`⚠️  Download validation completed with errors: ${error.message}`);
        }

        // Step 6: Process JSON files and convert to CSV
        console.log('Step 6: Processing JSON files to CSV...');
        

        // Use storage folder from settings + client name
        const folderPath = path.join(storageFolder, 'Legend', 'JSON');
        const filePattern = new RegExp(`.*${runName}.*\\.json$`);
        console.log("Inputs for process JSON files:", "|Folder Path = ",folderPath,"|filePattern = ",filePattern)
        
        try {
            await processJSONFilesSummaryTotalOnly(
                folderPath,
                filePattern,
                runName // Use runName as optional folder
            );
            console.log('JSON to CSV processing completed');
        } catch (error) {
            console.log(`⚠️  JSON processing completed with errors: ${error.message}`);
        }

        // Step 7: Concatenate CSV files
        console.log('Step 7: Concatenating CSV files...');
        
        const csvFolderPath = path.join(path.dirname(folderPath), 'CSV', runName);

        const csvFilePattern = `${runName}.*\\.csv$`;
        const outputFilePath = `./reportSuiteChecks/ReportSuiteValidation_${runName}.csv`;

        try {
            await concatenateCSVs(
                csvFolderPath,
                csvFilePattern,
                outputFilePath
            );
            console.log('CSV concatenation completed');
            console.log(`Final output saved to: ${outputFilePath}`);
        } catch (error) {
            console.log(`⚠️  CSV concatenation completed with errors: ${error.message}`);
        }
        // Step 8: Process CSV for bot investigation and validation lists
        console.log('Step 8: Processing CSV for bot investigation and validation lists...');
        
        try {
            // Read the concatenated CSV file
            const csvContent = fs.readFileSync(outputFilePath, 'utf8');
            const lines = csvContent.split('\n');
            const header = lines[0];
            const dataLines = lines.slice(1).filter(line => line.trim() !== '');
            
            // Parse CSV data
            const csvData = dataLines.map(line => {
                const values = line.split(',');
                return {
                    unique_visitors: parseInt(values[0]) || 0,
                    visits: parseInt(values[1]) || 0,
                    fileName: values[2] ? values[2].replace(/"/g, '') : '', // Remove quotes
                    fromDate: values[3] ? values[3].replace(/"/g, '') : '',
                    toDate: values[4] ? values[4].replace(/"/g, '') : ''
                };
            });
            
            // Extract RSID names from fileName (between 3rd and 4th underscores)
            const extractRsidName = (fileName) => {
                const parts = fileName.split('_');
                return parts.length > 3 ? parts[3] : '';
            };
            
            // Add RSID name to each row for easier filtering
            const csvDataWithRsid = csvData.map(row => ({
                ...row,
                rsidName: extractRsidName(row.fileName)
            }));
            
            // Filter out excluded RSID clean names first
            const filteredCsvData = csvDataWithRsid.filter(row => {
                const isExcluded = excludedRsidCleanNames.includes(row.rsidName);
                if (isExcluded) {
                    console.log(`🚫 Excluding ${row.rsidName} (in exclusion list)`);
                }
                return !isExcluded;
            });
            
            console.log(`Filtered out ${csvData.length - filteredCsvData.length} report suites from exclusion list`);
            console.log(`Remaining report suites for threshold filtering: ${filteredCsvData.length}`);
            
            // Filter for investigation threshold
            const investigationFiltered = filteredCsvData.filter(row => row.visits >= minimumVisitsInvestigation);
            console.log(`Found ${investigationFiltered.length} report suites meeting investigation threshold (${minimumVisitsInvestigation} visits)`);
            
            // Filter for validation threshold
            const validationFiltered = filteredCsvData.filter(row => row.visits >= minimumVisitsValidation);
            console.log(`Found ${validationFiltered.length} report suites meeting validation threshold (${minimumVisitsValidation} visits)`);
            
            // Create investigation RSID list
            const investigationRsidList = investigationFiltered
                .map(row => row.rsidName)
                .filter(rsid => rsid !== ''); // Remove empty strings
            
            // Create validation RSID list
            const validationRsidList = validationFiltered
                .map(row => row.rsidName)
                .filter(rsid => rsid !== ''); // Remove empty strings
            
            // Ensure directory exists
            const usefulInfoDir = './usefulInfo/Legend';
            if (!fs.existsSync(usefulInfoDir)) {
                fs.mkdirSync(usefulInfoDir, { recursive: true });
            }
            
            // Create investigation file content
            const investigationFileContent = `
//Minumum Threshold = ${minimumVisitsInvestigation}
//Date Range = ${fromDateStr} to ${toDateStr}
//File generated on ${todayStr}
//Excluded RSIDs: ${excludedRsidCleanNames.join(', ')}
const botInvestigationMinThresholdVisits = [
${investigationRsidList.map(rsid => `    '${rsid}'`).join(',\n')}
];

            module.exports = botInvestigationMinThresholdVisits;`;
            
            // Create validation file content
            const validationFileContent = `
//Minumum Threshold = ${minimumVisitsValidation}
//Date Range = ${fromDateStr} to ${toDateStr}
//File generated on ${todayStr}
//Excluded RSIDs: ${excludedRsidCleanNames.join(', ')}
const botValidationRsidList = [
${validationRsidList.map(rsid => `    '${rsid}'`).join(',\n')}
];

            module.exports = botValidationRsidList;`;
            
            // Write files
            const investigationFilePath = path.join(usefulInfoDir, 'botInvestigationMinThresholdVisits.js');
            const validationFilePath = path.join(usefulInfoDir, 'botValidationRsidList.js');
            
            fs.writeFileSync(investigationFilePath, investigationFileContent);
            fs.writeFileSync(validationFilePath, validationFileContent);
            
            console.log(`Investigation RSID list saved to: ${investigationFilePath}`);
            console.log(`Validation RSID list saved to: ${validationFilePath}`);
            console.log(`Investigation list contains ${investigationRsidList.length} RSIDs`);
            console.log(`Validation list contains ${validationRsidList.length} RSIDs`);
            
            } catch (error) {
                console.log(`⚠️  CSV processing for RSID lists completed with errors: ${error.message}`);
            }

        console.log('🎉 LegendReportSuiteUpdater completed!');

    process.exit = originalExit;

    // Explicitly exit the process when all operations are complete
    process.exit(0);
     
    } catch (error) {
        console.error('💥 Error in LegendReportSuiteUpdater:', error);
        process.exit = originalExit; // Restore original exit
        throw error;
    }
}

module.exports = LegendReportSuiteUpdater;