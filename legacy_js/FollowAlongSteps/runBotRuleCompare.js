#!/usr/bin/env node

/**
 * Standalone Bot Rule Comparison Script (OPTIMIZED VERSION)
 * 
 * This script processes multiple RSIDs to compare bot rule segment traffic
 * against all traffic across suspicious dimensions.
 * 
 * OPTIMIZATION: When processing multiple bot rules with the same date range,
 * AllTraffic reports are downloaded once for the first rule, then copied for
 * subsequent rules. This can reduce API calls by 33-45% depending on the
 * number of rules being processed.
 * 
 * USAGE:
 * node FollowAlongSteps\runBotRuleComparison.js
 * 
 * CONFIGURATION:
 * Edit the CONFIG section below to customize your analysis.
 * 
 * PERFORMANCE TIP:
 * For maximum efficiency when processing multiple bot rules:
 * - Use CSV Batch Mode (processes rules sequentially)
 * - Use consistent date ranges across rules
 * - First rule downloads AllTraffic files (~9 downloads per RSID)
 * - Subsequent rules copy existing AllTraffic files (~9 copies per RSID)
 * - Result: Significant reduction in API calls and processing time
 */

const processBotRuleComparison = require('../processBotRuleComparison');

// ============================================================================
// CONFIGURATION - Edit these values for your analysis
// ============================================================================

const CONFIG = {
    // Date Range
    fromDate: '2024-02-01',                     // Start date (YYYY-MM-DD)
    toDate: '2026-02-01',                       // End date (YYYY-MM-DD, should be following day)
    
    // ========================================================================
    // PROCESSING MODE - Choose ONE of the following modes:
    // ========================================================================
    
    // MODE 1: CSV Batch Processing (RECOMMENDED for multiple rules)
    // This mode maximizes optimization benefits by processing rules sequentially
    // First rule downloads AllTraffic files, subsequent rules copy them
    csvBatchMode: true,
    csvFileName: 'Oddspedia-AdHoc-Jan26-RoundFiveV3_compare.csv',    // CSV file name in '../usefulInfo/Legend/BotCompareLists'
    comparisonRound: 1.0,                      // Version number for this comparison run
    // CSV must have columns: dimSegmentId, botRuleName, reportToIgnore
    // All rules will use the rsid list specified below
    
    // MODE 2: Single Bot Rule Configuration
    // Use this for testing or one-off comparisons
    // // Uncomment this section for traditional single-rule processing
    // reportToSkip: 'botInvestigationMetricsByPageURL',  // Dimension used in your bot rule
    // segmentId: 's3938_692477a0347b1f4a2a1976bd',      // Your bot rule segment ID
    // segmentName: 'coversSuspiciousPromoCodeURLs',   // Descriptive name for your rule
    // comparisonRound: 1.0,                       // Version number for this comparison run
    
    // ========================================================================
    // OPTIMIZATION SETTINGS (New!)
    // ========================================================================
    
    // Enable AllTraffic file caching (default: true)
    // When enabled, AllTraffic files are copied instead of re-downloaded
    enableAllTrafficCaching: true,              // Set to false to disable optimization
    
    // Show detailed optimization statistics in output
    showOptimizationStats: true,                // Shows downloads vs copies
    
    // ========================================================================
    // RSID Configuration - Used by ALL processing modes
    // ========================================================================
    
    // Choose ONE of the following options:
    
    // OPTION 1: Use a file containing RSID list (recommended for large lists)
    rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
    
    // OPTION 2: Provide specific RSIDs as an array (uncomment to use)
    // rsidCleanNameList: [
    //     'OnlineCasinoca',
    // ],
    
    // OPTION 3: Different segments per RSID (only for MODE 2 - single rule)
    // rsidConfigList: [
    //     { cleanName: 'OnlineSlotsca', segmentId: 's123_abc', segmentName: 'Canada-Rule' },
    //     { cleanName: 'Casinoguru', segmentId: 's123_def', segmentName: 'Global-Rule' },
    //     { cleanName: 'coverscom', segmentId: 's123_ghi', segmentName: 'Philippines-Rule' }
    // ],
    
    // ========================================================================
    // Optional Settings
    // ========================================================================
    clientName: 'Legend',                       // Adobe Analytics client name
    logDir: './temp',                           // Directory for log files
    enableStatusReporting: true,                // Show periodic status updates
    statusReportingInterval: 30000,             // Status update interval (ms)
    legendRsidLookupPath: './usefulInfo/Legend/legendReportSuites.txt'
};

// ============================================================================
// EXECUTION
// ============================================================================

console.log('🚀 Starting Bot Rule Comparison (Optimized)');
console.log('==========================================');
console.log(`📅 Date Range: ${CONFIG.fromDate} to ${CONFIG.toDate}`);

if (CONFIG.csvBatchMode) {
    console.log('📋 Mode: CSV Batch Processing');
    console.log(`📄 CSV File: ${CONFIG.csvFileName}`);
    if (CONFIG.enableAllTrafficCaching !== false) {
        console.log('⚡ Optimization: Enabled (AllTraffic caching active)');
        console.log('💡 First rule downloads AllTraffic, subsequent rules copy');
    } else {
        console.log('⚠️  Optimization: Disabled (will download all files)');
    }
} else {
    console.log('📋 Mode: Single Rule Processing');
    console.log(`🎯 Segment: ${CONFIG.segmentName} (${CONFIG.segmentId})`);
    console.log(`📊 Skipping Dimension: ${CONFIG.reportToSkip}`);
}

console.log(`🔄 Comparison Round: ${CONFIG.comparisonRound}`);
console.log('==========================================\n');

// Track timing for performance metrics
const startTime = Date.now();

processBotRuleComparison(CONFIG)
    .then(result => {
        const endTime = Date.now();
        const durationSeconds = ((endTime - startTime) / 1000).toFixed(2);
        const durationMinutes = ((endTime - startTime) / 60000).toFixed(2);
        
        console.log('\n✨ Processing Complete!');
        console.log('======================');
        console.log(`✅ Successfully Processed: ${result.processed}`);
        console.log(`❌ Failed: ${result.failed}`);
        console.log(`📈 Success Rate: ${((result.processed / (result.processed + result.failed)) * 100).toFixed(2)}%`);
        console.log(`⏱️  Total Duration: ${durationMinutes} minutes (${durationSeconds} seconds)`);
        console.log(`📝 Log File: ${result.logFilePath}`);
        console.log(`🔢 Run Number: ${result.runNumber}`);
        
        // Show optimization statistics if available and enabled
        if (CONFIG.showOptimizationStats && result.optimizationStats) {
            console.log('\n🎉 Optimization Impact:');
            console.log('----------------------');
            console.log(`📥 AllTraffic Downloads: ${result.optimizationStats.allTrafficDownloaded || 0}`);
            console.log(`📋 AllTraffic Copies: ${result.optimizationStats.allTrafficCopied || 0}`);
            console.log(`💾 API Calls Saved: ${result.optimizationStats.allTrafficCopied || 0}`);
            
            const totalAllTraffic = (result.optimizationStats.allTrafficDownloaded || 0) + 
                                   (result.optimizationStats.allTrafficCopied || 0);
            if (totalAllTraffic > 0) {
                const percentSaved = ((result.optimizationStats.allTrafficCopied / totalAllTraffic) * 100).toFixed(1);
                console.log(`📊 AllTraffic Download Reduction: ${percentSaved}%`);
            }
        }
        
        if (result.errors && result.errors.length > 0) {
            console.log('\n⚠️  Errors Encountered:');
            result.errors.forEach((error, index) => {
                console.log(`  ${index + 1}. ${error.rsidCleanName || error.ruleName} (${error.rsid || 'N/A'}): ${error.message}`);
            });
        }
        
        console.log('\n======================');
        process.exit(result.success ? 0 : 1);
    })
    .catch(error => {
        const endTime = Date.now();
        const durationSeconds = ((endTime - startTime) / 1000).toFixed(2);
        
        console.error('\n💥 Fatal Error:');
        console.error(error);
        console.error('\nStack trace:');
        console.error(error.stack);
        console.error(`\n⏱️  Failed after ${durationSeconds} seconds`);
        process.exit(1);
    });

// ============================================================================
// QUICK CONFIGURATION TEMPLATES
// ============================================================================

/**
 * TEMPLATE 1: CSV Batch Processing (OPTIMIZED - RECOMMENDED)
 * 
 * Process multiple bot rules from a CSV file with maximum efficiency.
 * First rule downloads AllTraffic files, subsequent rules copy them.
 * 
 * Example savings with 3 rules × 20 RSIDs:
 * - Without optimization: 3 × 20 × 9 = 540 AllTraffic downloads
 * - With optimization: 20 × 9 = 180 AllTraffic downloads + 360 copies
 * - API calls saved: 360 (67% reduction in AllTraffic downloads)
 */
/*
const CSV_BATCH_OPTIMIZED = {
    fromDate: '2025-02-01',
    toDate: '2025-05-31',
    csvBatchMode: true,
    csvFileName: 'BotCompareFebMay25.csv',
    comparisonRound: 1.0,
    rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
    enableAllTrafficCaching: true,              // Enable optimization
    showOptimizationStats: true,                // Show savings
    enableStatusReporting: true
};

processBotRuleComparison(CSV_BATCH_OPTIMIZED)
    .then(result => {
        console.log('CSV batch processing complete:', result);
        console.log(`API calls saved: ${result.optimizationStats?.allTrafficCopied || 0}`);
        process.exit(result.success ? 0 : 1);
    });
*/

/**
 * TEMPLATE 2: Single RSID Quick Test
 * 
 * Uncomment and modify this section to quickly test a single RSID.
 * Optimization has minimal impact for single rules but still works.
 */
/*
const QUICK_TEST_CONFIG = {
    fromDate: '2025-01-01',
    toDate: '2025-01-31',
    reportToSkip: 'botInvestigationMetricsByDomain',
    segmentId: 's3938_6780ffad8e0db45770364b00',
    segmentName: 'Test-Rule',
    comparisonRound: 0.1,
    rsidCleanNameList: ['coverscom'],
    enableStatusReporting: false,
    enableAllTrafficCaching: true               // Always safe to enable
};

processBotRuleComparison(QUICK_TEST_CONFIG)
    .then(result => {
        console.log('Quick test complete:', result);
        process.exit(result.success ? 0 : 1);
    });
*/

/**
 * TEMPLATE 3: High-Volume Analysis (OPTIMIZED)
 * 
 * For processing many RSIDs over a long time period.
 * Optimization provides significant time and API call savings.
 * 
 * Example with 50 RSIDs × 1 year of data:
 * - Downloads: ~450 files for first rule
 * - Copies: ~450 files for subsequent rules (much faster than downloading)
 * - Time saved: 15-20 minutes per additional rule
 */
/*
const HIGH_VOLUME_CONFIG = {
    fromDate: '2024-01-01',
    toDate: '2025-01-01',
    reportToSkip: 'botInvestigationMetricsByUserAgent',
    segmentId: 's3938_xyz',
    segmentName: 'BotUA-Pattern',
    comparisonRound: 2.0,
    rsidListPath: './usefulInfo/Legend/botInvestigationMinThresholdVisits.js',
    enableAllTrafficCaching: true,              // Critical for high-volume!
    showOptimizationStats: true,
    enableStatusReporting: true,
    statusReportingInterval: 15000              // More frequent updates
};
*/

/**
 * TEMPLATE 4: Multi-Segment Analysis (OPTIMIZED)
 * 
 * For comparing different bot rules across specific RSIDs.
 * Each RSID/segment combination is processed, but AllTraffic files
 * are shared when possible (same RSID, same date range).
 */
/*
const MULTI_SEGMENT_CONFIG = {
    fromDate: '2025-01-01',
    toDate: '2025-03-31',
    reportToSkip: 'botInvestigationMetricsByRegion',
    comparisonRound: 1.0,
    enableAllTrafficCaching: true,
    showOptimizationStats: true,
    rsidConfigList: [
        { 
            cleanName: 'OnlineSlotsca', 
            segmentId: 's123_canada_bots', 
            segmentName: 'CA-BotPattern' 
        },
        { 
            cleanName: 'OnlineCasinocouk', 
            segmentId: 's123_uk_bots', 
            segmentName: 'UK-BotPattern' 
        },
        { 
            cleanName: 'OnlineCasinosde', 
            segmentId: 's123_de_bots', 
            segmentName: 'DE-BotPattern' 
        }
    ]
};
*/

/**
 * TEMPLATE 5: Debug Mode (Optimization Disabled)
 * 
 * Use this configuration when troubleshooting or comparing results.
 * Disables optimization to ensure fresh downloads of all files.
 */
/*
const DEBUG_CONFIG = {
    fromDate: '2025-01-01',
    toDate: '2025-01-31',
    reportToSkip: 'botInvestigationMetricsByDomain',
    segmentId: 's3938_debug',
    segmentName: 'Debug-Rule',
    comparisonRound: 0.1,
    rsidCleanNameList: ['coverscom'],
    enableAllTrafficCaching: false,             // Disable optimization
    showOptimizationStats: false,
    enableStatusReporting: true
};
*/

// ============================================================================
// OPTIMIZATION BEST PRACTICES
// ============================================================================

/*
 * MAXIMIZING EFFICIENCY:
 * 
 * 1. USE CSV BATCH MODE
 *    - Processes rules sequentially
 *    - First rule downloads, subsequent rules copy
 *    - Automatic optimization with zero configuration
 * 
 * 2. CONSISTENT DATE RANGES
 *    - AllTraffic caching works best with same date ranges
 *    - If rules have different dates, they'll still download when needed
 * 
 * 3. SEQUENTIAL PROCESSING
 *    - The script already does this in CSV batch mode
 *    - Don't run multiple instances simultaneously
 * 
 * 4. MONITOR STATISTICS
 *    - Enable showOptimizationStats: true
 *    - Watch for high copy counts (good!)
 *    - Low copy counts might indicate:
 *      * Different date ranges per rule
 *      * File copy errors (check logs)
 *      * First run (expected - no files to copy yet)
 * 
 * 5. VALIDATION AFTER PROCESSING
 *    - Always run validateBotRuleComparisons after
 *    - Copied files are validated the same as downloaded files
 *    - Missing files will be automatically re-downloaded
 * 
 * EXPECTED SAVINGS:
 * - 2 rules: ~33% API call reduction for AllTraffic
 * - 3 rules: ~50% API call reduction for AllTraffic  
 * - 5 rules: ~60% API call reduction for AllTraffic
 * - 10 rules: ~70% API call reduction for AllTraffic
 * 
 * TIME SAVINGS:
 * - Each AllTraffic file download: ~5-10 seconds
 * - Each AllTraffic file copy: <1 second
 * - For 100 AllTraffic files: Save ~8-15 minutes per rule (after first)
 */