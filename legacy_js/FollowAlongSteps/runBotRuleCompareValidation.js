#!/usr/bin/env node

/**
 * Bot Rule Comparison Validation Script
 * 
 * This script validates that all expected files from bot rule comparisons have been
 * downloaded correctly. It can automatically re-download any missing files.
 * 
 * USAGE:
 * node FollowAlongSteps\runBotRuleValidation.js
 * 
 * CONFIGURATION:
 * Edit the CONFIG section below to match your bot rule comparison settings.
 * Use the SAME configuration as your runBotRuleComparison.js to validate those files.
 */

const validateBotRuleComparisons = require('../validateBotRuleComparisons');

// ============================================================================
// CONFIGURATION - Should match your runBotRuleComparison.js settings
// ============================================================================

const CONFIG = {
    
    // ========================================================================
    // VALIDATION MODE
    // ========================================================================
    
    // Set to true for dry run (check only, don't re-download)
    // Set to false to automatically re-download missing files

    dryRun: false,

    // Date Range (must match your comparison run)
    fromDate: '2024-02-01',
    toDate: '2026-02-01',

    
    // ========================================================================
    // PROCESSING MODE - Must match your comparison configuration
    // ========================================================================
    
    // MODE 1: CSV Batch Processing
    // Uncomment if you used CSV batch mode
    csvBatchMode: true,
    csvFileName: 'Oddspedia-AdHoc-Jan26-RoundFiveV3_compare.csv',    // CSV file name in '../usefulInfo/Legend/BotCompareLists'
    comparisonRound: 1.0,                      // Version number for this comparison run
    
    // MODE 2: Single Bot Rule Configuration
    // Uncomment if you used single rule mode
    // reportToSkip: 'botInvestigationMetricsByPageURL',
    // segmentId: 's3938_692477a0347b1f4a2a1976bd',
    // segmentName: 'coversSuspiciousPromoCodeURLs',
    // comparisonRound: 1.0,
    
    // ========================================================================
    // RSID Configuration - Must match your comparison
    // ========================================================================
    
    // Use the SAME RSID configuration as your comparison run
    // rsidCleanNameList: [
    //     'OnlineCasinoca',
    // ],
    
    // // // Or use the same RSID list file:
    rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
    
    // Or use RSID-specific configurations:
    // rsidConfigList: [
    //     { cleanName: 'OnlineSlotsca', segmentId: 's123_abc', segmentName: 'Canada-Rule' },
    //     { cleanName: 'Casinoguru', segmentId: 's123_def', segmentName: 'Global-Rule' },
    // ],
    
    // ========================================================================
    // Optional Settings
    // ========================================================================
    clientName: 'Legend',
    logDir: './temp',
    enableStatusReporting: true,
    statusReportingInterval: 30000,
    legendRsidLookupPath: './usefulInfo/Legend/legendReportSuites.txt',
    readWriteConfigPath: './config/read_write_settings/readWriteSettings.yaml'
};

// ============================================================================
// EXECUTION
// ============================================================================

console.log('🔍 Starting Bot Rule Comparison Validation');
console.log('==========================================');
console.log(`📅 Date Range: ${CONFIG.fromDate} to ${CONFIG.toDate}`);
console.log(`🎯 Mode: ${CONFIG.dryRun ? 'DRY RUN (check only)' : 'ACTIVE (will re-download)'}`);

if (CONFIG.csvBatchMode) {
    console.log('📋 Processing Mode: CSV Batch');
    console.log(`📄 CSV File: ${CONFIG.csvFileName}`);
} else {
    console.log('📋 Processing Mode: Single Rule');
    console.log(`🎯 Segment: ${CONFIG.segmentName} (${CONFIG.segmentId})`);
    console.log(`📊 Skipping Dimension: ${CONFIG.reportToSkip}`);
}

console.log(`🔄 Comparison Round: ${CONFIG.comparisonRound}`);
console.log('==========================================\n');

validateBotRuleComparisons(CONFIG)
    .then(result => {
        console.log('\n✨ Validation Complete!');
        console.log('======================');
        console.log(`📊 Comparisons Checked: ${result.comparisonsChecked}`);
        console.log(`📁 Total Files Expected: ${result.totalFilesExpected}`);
        console.log(`✅ Files Found: ${result.filesFound}`);
        console.log(`❌ Files Missing: ${result.filesMissing}`);
        
        if (!CONFIG.dryRun) {
            console.log(`📥 Files Re-downloaded: ${result.filesRedownloaded}`);
            console.log(`⚠️  Failed Re-downloads: ${result.failedRedownloads}`);
        }
        
        console.log(`📈 Completeness: ${((result.filesFound / result.totalFilesExpected) * 100).toFixed(2)}%`);
        console.log(`📝 Log File: ${result.logFilePath}`);
        console.log(`📄 Expected Files List: ${result.expectedFilesPath}`);
        console.log(`🔢 Run Number: ${result.runNumber}`);
        
        if (result.filesMissing > 0 && CONFIG.dryRun) {
            console.log('\n💡 TIP: Set dryRun: false to automatically re-download missing files');
        }
        
        if (result.errors.length > 0) {
            console.log('\n⚠️  Errors Encountered:');
            result.errors.forEach((error, index) => {
                console.log(`  ${index + 1}. ${error.comparison}: ${error.file} - ${error.error}`);
            });
        }
        
        if (result.filesMissing === 0) {
            console.log('\n🎉 All files are present and accounted for!');
        } else if (CONFIG.dryRun) {
            console.log('\n⚠️  Missing files detected. Run with dryRun: false to re-download.');
        } else if (result.failedRedownloads === 0) {
            console.log('\n🎉 All missing files have been successfully re-downloaded!');
        }
        
        console.log('\n======================');
        process.exit(result.success && result.filesMissing === 0 ? 0 : 1);
    })
    .catch(error => {
        console.error('\n💥 Fatal Error:');
        console.error(error);
        console.error('\nStack trace:');
        console.error(error.stack);
        process.exit(1);
    });

// ============================================================================
// QUICK CONFIGURATION TEMPLATES
// ============================================================================

/**
 * TEMPLATE 1: Dry Run Validation (Check Only)
 * 
 * Use this to see which files are missing without re-downloading:
 */
/*
const DRY_RUN_CONFIG = {
    fromDate: '2025-02-01',
    toDate: '2025-05-31',
    dryRun: true,  // Just check, don't download
    csvBatchMode: true,
    csvFileName: 'BotCompareFebMay25.csv',
    comparisonRound: 1.0,
    rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js'
};

validateBotRuleComparisons(DRY_RUN_CONFIG)
    .then(result => {
        console.log('Dry run complete. Missing files:', result.filesMissing);
        process.exit(0);
    });
*/

/**
 * TEMPLATE 2: Active Re-download
 * 
 * Use this to automatically re-download any missing files:
 */
/*
const ACTIVE_REDOWNLOAD_CONFIG = {
    fromDate: '2025-02-01',
    toDate: '2025-05-31',
    dryRun: false,  // Will re-download missing files
    csvBatchMode: true,
    csvFileName: 'BotCompareFebMay25.csv',
    comparisonRound: 1.0,
    rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
    enableStatusReporting: true
};

validateBotRuleComparisons(ACTIVE_REDOWNLOAD_CONFIG)
    .then(result => {
        console.log('Re-download complete:', result);
        process.exit(result.success ? 0 : 1);
    });
*/

/**
 * TEMPLATE 3: Validate Single Comparison
 * 
 * For checking a single RSID/segment combination:
 */
/*
const SINGLE_VALIDATION_CONFIG = {
    fromDate: '2025-01-01',
    toDate: '2025-01-31',
    dryRun: true,
    reportToSkip: 'botInvestigationMetricsByUserAgent',
    segmentId: 's3938_xyz',
    segmentName: 'Test-Rule',
    comparisonRound: 1.0,
    rsidCleanNameList: ['coverscom']
};
*/

/**
 * TEMPLATE 4: Scheduled Validation
 * 
 * For periodic checks (could be run as a cron job):
 */
/*
const SCHEDULED_VALIDATION_CONFIG = {
    fromDate: '2025-01-01',
    toDate: '2025-03-31',
    dryRun: false,  // Auto-fix any issues
    csvBatchMode: true,
    csvFileName: 'ProductionRules.csv',
    comparisonRound: 1.0,
    rsidListPath: './usefulInfo/Legend/productionRsids.js',
    enableStatusReporting: false  // Less verbose for automated runs
};
*/
