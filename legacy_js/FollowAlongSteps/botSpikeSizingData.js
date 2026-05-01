// ============================================
// CONFIGURATION PARAMETERS - Edit these as needed
// ============================================
const requestName = 'botInvestigationMetricsByDay';
const reportedStartDate = '2026-01-01';
const reportedEndDate = '2026-01-31';
const clientName = 'Legend';
const suite = 'Casinoorg';
const additionalSegment = '69822edfc4cda662376d33e2'; // BSS001 - Corg News and China or Singapore (or set to undefined)
const optionalFolder = 'BotSpikeSizing'; // Optional subdirectory within the CSV folder
const downloadTimeout = 300000; // Timeout in ms (adjust for larger requests - up to 300000 for 5 min)

// ============================================
// DEPENDENCIES
// ============================================
const downloadAdobeTable = require('../downloadAdobeTable');
const processJSONFiles = require('../processJSONFiles');
const subtractDays = require('../utils/subtractDays');
const retrieveLegendRsid = require('../utils/retrieveLegendRsid');
const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath');

// ============================================
// MAIN EXECUTION
// ============================================
(async () => {
    try {
        // Calculate date range
        const reportFromDate = subtractDays(reportedStartDate, 455); // Subtract to capture backfilled data
        const reportToDate = subtractDays(reportedEndDate,-30);
        
        // Get RSID
        const rsid = retrieveLegendRsid(suite);
        console.log('RSID:', rsid);
        
        // Step 1: Download Adobe Table(s)
        if (additionalSegment) {
            // Download TWO tables in parallel: one with segment, one without
            console.log('Starting parallel downloads (with and without segment)...');
            await Promise.all([
                new Promise((resolve) => {
                    console.log('Downloading table WITH segment...');
                    downloadAdobeTable(reportFromDate, reportToDate, requestName, clientName, additionalSegment, rsid);
                    setTimeout(resolve, downloadTimeout);
                }),
                new Promise((resolve) => {
                    console.log('Downloading table WITHOUT segment...');
                    downloadAdobeTable(reportFromDate, reportToDate, requestName, clientName, undefined, rsid);
                    setTimeout(resolve, downloadTimeout);
                })
            ]);
            console.log('Both downloads completed');
        } else {
            // Download ONE table without segment
            console.log('Starting download (no segment)...');
            await new Promise((resolve) => {
                downloadAdobeTable(reportFromDate, reportToDate, requestName, clientName, undefined, rsid);
                setTimeout(resolve, downloadTimeout);
            });
            console.log('Download completed');
        }
        
        // Step 2: Process JSON Files
        console.log('Starting file processing...');
        
        // Use wildcard pattern to match both files (with and without DIMSEG)
        const filePatternString = `${requestName}_.*${reportFromDate}_${reportToDate}.json`;
        const filePattern = new RegExp(filePatternString + '$');
        console.log('File pattern:', filePattern);
        
        const folderPath = getJsonStorageFolderPath(clientName);
        await processJSONFiles(folderPath, filePattern, optionalFolder);
        
        console.log('All operations completed successfully!');
        process.exit(0);
        
    } catch (error) {
        console.error('Error during execution:', error);
        process.exit(1);
    }
})();