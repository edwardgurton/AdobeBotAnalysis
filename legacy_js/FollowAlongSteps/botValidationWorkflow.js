// botValidationWorkflow.js - Complete optimized workflow for bot validation
const readBotRulesFromCSV = require('./readBotRulesFromCSV');
const { processBotRules } = require('./downloadBotRuleValidationData');
const { validateMultipleBotRules } = require('./validateBotValidationDownload');
const botValidationTransformConcat = require('./botValidationTransformConcat');

/**
 * Complete bot validation workflow with all steps
 * @param {string} csvFileName - CSV file containing bot rules (e.g., 'myBotRules.csv')
 * @param {string} fromDate - Start date in YYYY-MM-DD format
 * @param {string} toDate - End date in YYYY-MM-DD format
 * @param {Object} options - Configuration options
 */
async function runCompleteBotValidationWorkflow(csvFileName, fromDate, toDate, options = {}) {
    const {
        clientName = 'Legend',
        validateDownload = true,
        redownloadMissing = true,
        runTransform = true
    } = options;

    console.log('\n╔═══════════════════════════════════════════════════════╗');
    console.log('║     BOT VALIDATION COMPLETE WORKFLOW (OPTIMIZED)     ║');
    console.log('╚═══════════════════════════════════════════════════════╝\n');
    console.log(`📁 CSV File: ${csvFileName}`);
    console.log(`📅 Date Range: ${fromDate} to ${toDate}`);
    console.log(`🏢 Client: ${clientName}\n`);

    try {
        // ═══════════════════════════════════════════════════════════
        // STEP 1: Read bot rules from CSV
        // ═══════════════════════════════════════════════════════════
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        console.log('📖 STEP 1: Reading bot rules from CSV...');
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
        
        const botRulesForDownload = readBotRulesFromCSV(csvFileName, 'download');
        const botRulesForTransform = readBotRulesFromCSV(csvFileName, 'transform');
        
        console.log(`✅ Loaded ${botRulesForDownload.length} bot rules for processing\n`);

        // ═══════════════════════════════════════════════════════════
        // STEP 2: Download data with optimization (shared reports only once)
        // ═══════════════════════════════════════════════════════════
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        console.log('📥 STEP 2: Downloading bot validation data (optimized)...');
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
        console.log('ℹ️  Optimization: Shared reports will be downloaded once and reused');
        console.log('ℹ️  This saves time when processing multiple bot rules\n');
        
        await processBotRules(botRulesForDownload, fromDate, toDate, clientName, {
            downloadShared: true,  // Download shared reports once
            copyShared: true       // Copy shared reports for each bot rule
        });
        
        console.log('\n✅ Download completed successfully\n');

        // ═══════════════════════════════════════════════════════════
        // STEP 3: Validate downloaded files and fix missing ones
        // ═══════════════════════════════════════════════════════════
        if (validateDownload) {
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
            console.log('🔍 STEP 3: Validating downloaded files...');
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
            
            // Use exitOnCompletion: false to prevent process.exit and continue to next step
            const validationOptions = {
                redownloadMissing: redownloadMissing,
                exitOnCompletion: false  // Critical: don't exit after validation
            };
            
            // Validate each bot rule
            for (let i = 0; i < botRulesForDownload.length; i++) {
                const botRule = botRulesForDownload[i];
                console.log(`\n[${i + 1}/${botRulesForDownload.length}] Validating: ${botRule.botRuleName}`);
                
                try {
                    const result = await require('./validateBotValidationDownload').validateBotValidationDownload(
                        fromDate,
                        toDate,
                        botRule.botRuleName,
                        botRule.dimSegmentId,
                        validationOptions
                    );
                    
                    if (result.isComplete) {
                        console.log(`✅ ${botRule.botRuleName}: All files present`);
                    } else {
                        console.log(`⚠️  ${botRule.botRuleName}: ${result.missingFiles + result.missingSharedReports} files were recovered`);
                    }
                } catch (error) {
                    console.error(`❌ Validation failed for ${botRule.botRuleName}:`, error.message);
                    throw error;
                }
            }
            
            console.log('\n✅ Validation completed for all bot rules\n');
        }

        // ═══════════════════════════════════════════════════════════
        // STEP 4: Transform JSON to CSV and concatenate
        // ═══════════════════════════════════════════════════════════
        if (runTransform) {
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
            console.log('🔄 STEP 4: Transforming and concatenating data...');
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
            
            await botValidationTransformConcat(clientName, botRulesForTransform);
            
            console.log('\n✅ Transform and concatenation completed\n');
        }

        // ═══════════════════════════════════════════════════════════
        // WORKFLOW COMPLETE
        // ═══════════════════════════════════════════════════════════
        console.log('╔═══════════════════════════════════════════════════════╗');
        console.log('║           🎉 WORKFLOW COMPLETED SUCCESSFULLY          ║');
        console.log('╚═══════════════════════════════════════════════════════╝\n');
        
        console.log('📊 Summary:');
        console.log(`   • Bot rules processed: ${botRulesForDownload.length}`);
        console.log(`   • Date range: ${fromDate} to ${toDate}`);
        console.log(`   • Client: ${clientName}`);
        console.log(`   • Validation: ${validateDownload ? 'Yes' : 'Skipped'}`);
        console.log(`   • Transform: ${runTransform ? 'Yes' : 'Skipped'}`);
        
        console.log('\n💡 Optimization Benefits:');
        const sharedReportsCount = 2; // botFilterExcludeMetricsByMonth and botFilterIncludeMetricsByMonth
        const rsidCount = require('./usefulInfo/Legend/botValidationRsidList.js').length;
        const savedDownloads = (botRulesForDownload.length - 1) * sharedReportsCount * rsidCount;
        console.log(`   • Saved ${savedDownloads} redundant downloads by sharing reports`);
        console.log(`   • Processing time reduced significantly for multiple bot rules\n`);

        process.exit(0);

    } catch (error) {
        console.error('\n╔═══════════════════════════════════════════════════════╗');
        console.error('║              ❌ WORKFLOW FAILED                       ║');
        console.error('╚═══════════════════════════════════════════════════════╝\n');
        console.error('Error:', error.message);
        console.error('\nStack trace:', error.stack);
        process.exit(1);
    }
}

/**
 * Simpler workflow for just download + validate
 */
async function runDownloadAndValidate(csvFileName, fromDate, toDate, clientName = 'Legend') {
    console.log('\n🚀 Running download and validate workflow...\n');
    
    await runCompleteBotValidationWorkflow(csvFileName, fromDate, toDate, {
        clientName,
        validateDownload: true,
        redownloadMissing: true,
        runTransform: false  // Skip transform step
    });
}

/**
 * Workflow for just transform (assumes data already downloaded)
 */
async function runTransformOnly(csvFileName, clientName = 'Legend') {
    console.log('\n🔄 Running transform-only workflow...\n');
    
    try {
        const botRulesForTransform = readBotRulesFromCSV(csvFileName, 'transform');
        await botValidationTransformConcat(clientName, botRulesForTransform);
        
        console.log('\n✅ Transform completed successfully\n');
        process.exit(0);
    } catch (error) {
        console.error('\n❌ Transform failed:', error.message);
        process.exit(1);
    }
}

// Export functions
module.exports = {
    runCompleteBotValidationWorkflow,
    runDownloadAndValidate,
    runTransformOnly
};

// Execute if run directly
if (require.main === module) {
    // Example usage - customize as needed:
    
    // Option 1: Complete workflow (download, validate, transform)
    runCompleteBotValidationWorkflow(
        'myBotRules.csv',      // Your CSV file with bot rules
        '2023-08-01',          // From date
        '2025-08-01',          // To date
        {
            clientName: 'Legend',
            validateDownload: true,
            redownloadMissing: true,
            runTransform: true
        }
    ).catch(console.error);
    
    // Option 2: Download and validate only (uncomment to use)
    // runDownloadAndValidate('myBotRules.csv', '2023-08-01', '2025-08-01')
    //     .catch(console.error);
    
    // Option 3: Transform only (uncomment to use)
    // runTransformOnly('myBotRules.csv', 'Legend')
    //     .catch(console.error);
}