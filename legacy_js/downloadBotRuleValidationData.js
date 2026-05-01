// downloadBotRuleValidationData.js - Optimized version
const iterateRsidRequests = require('./utils/iterateRsidRequests.js');
const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

// Get storage folder from config
let storageFolder;
try {
    const readWriteSettings = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
    storageFolder = readWriteSettings.storage.folder;
} catch (error) {
    console.error('Error loading storage folder from config:', error);
    storageFolder = './storage'; // fallback
}

// Shared reports that don't use bot rules
const SHARED_REPORTS = [
    'botFilterExcludeMetricsByMonth',
    'botFilterIncludeMetricsByMonth'
];

// Bot-specific reports that require dimSegmentId
const BOT_SPECIFIC_REPORTS = [
    'botFilterExcludexBotRuleMetricsByMonth',
    'botFilterIncludexBotRuleMetricsByMonth',
    'botFilterExcludexBotRuleXSuspiciousMarketingChannelsMetricsByMonth',
    'botFilterExcludexBotRuleXDesktopMetricsByMonth',
    'botFilterExcludexBotRuleMetricsByPageUrl'
];

// Simple wrapper that prevents process.exit from terminating everything
async function safeIterateRsidRequests(legendRsidList, fromDate, toDate, requestName, clientName, dimSegmentId, botRuleName) {
    const originalExit = process.exit;
    process.exit = (code) => {
        console.log(`iterateRsidRequests completed for ${requestName} (would have exited with code ${code})`);
        process.exit = originalExit;
    };
    
    try {
        await iterateRsidRequests(legendRsidList, fromDate, toDate, requestName, clientName, dimSegmentId, botRuleName);
    } catch (error) {
        process.exit = originalExit;
        throw error;
    }
}

/**
 * Downloads shared bot validation reports that don't depend on specific bot rules
 * These reports are the same for all bot rules and only need to be downloaded once
 */
async function downloadSharedBotValidationReports(legendRsidList, fromDate, toDate, clientName='Legend') {
    console.log(`\n📥 Downloading shared bot validation reports (once for all bot rules)...`);
    
    try {
        const requestPromises = SHARED_REPORTS.map(reportName => 
            safeIterateRsidRequests(legendRsidList, fromDate, toDate, reportName, clientName, undefined, 'SHARED')
        );
        
        await Promise.all(requestPromises);
        console.log(`✓ Shared reports downloaded successfully`);
        return true;
    } catch (error) {
        console.error(`Error downloading shared reports:`, error);
        throw error;
    }
}

/**
 * Copies shared report files and renames them for a specific bot rule
 * This allows each bot rule to have its own set of files without re-downloading
 */
async function copySharedReportsForBotRule(legendRsidList, fromDate, toDate, clientName, botRuleName) {
    console.log(`\n📋 Copying shared reports for bot rule: ${botRuleName}`);
    
    const jsonFolder = path.join(storageFolder, clientName, 'JSON');
    let copiedCount = 0;
    let skippedCount = 0;
    
    for (const reportName of SHARED_REPORTS) {
        for (const rsid of legendRsidList) {
            // Extract rsidCleanName from the rsid object (assuming format like legendRsidList)
            const rsidCleanName = typeof rsid === 'string' ? rsid : rsid.rsidCleanName || rsid;
            
            // Source file (shared)
            const sourcePattern = `${clientName}_${reportName}_SHARED_${rsidCleanName}_*${fromDate}_${toDate}.json`;
            
            // Destination file (bot-rule-specific)
            const destPattern = `${clientName}_${reportName}_${botRuleName}_${rsidCleanName}`;
            
            try {
                // Find the source file (it may have DIMSEG in the name)
                const files = fs.readdirSync(jsonFolder);
                const sourceFiles = files.filter(f => {
                    const regex = new RegExp(sourcePattern.replace(/\*/g, '.*'));
                    return regex.test(f);
                });
                
                if (sourceFiles.length === 0) {
                    console.warn(`⚠️  Source file not found for pattern: ${sourcePattern}`);
                    skippedCount++;
                    continue;
                }
                
                // Use the first matching file
                const sourceFile = sourceFiles[0];
                const sourcePath = path.join(jsonFolder, sourceFile);
                
                // Build destination filename (preserve DIMSEG part if it exists)
                const destFile = sourceFile.replace('_SHARED_', `_${botRuleName}_`);
                const destPath = path.join(jsonFolder, destFile);
                
                // Check if destination already exists
                if (fs.existsSync(destPath)) {
                    console.log(`   ⏭️  Already exists: ${destFile}`);
                    skippedCount++;
                    continue;
                }
                
                // Copy the file
                fs.copyFileSync(sourcePath, destPath);
                console.log(`   ✓ Copied: ${sourceFile} → ${destFile}`);
                copiedCount++;
                
            } catch (error) {
                console.error(`   ✗ Error copying ${reportName} for ${rsidCleanName}:`, error.message);
            }
        }
    }
    
    console.log(`✓ Copied ${copiedCount} files, skipped ${skippedCount} existing files for ${botRuleName}`);
}

/**
 * Downloads bot-specific validation data for a single bot rule
 * This now excludes the shared reports which are downloaded separately
 */
async function downloadBotRuleValidationData(fromDate, toDate, clientName='Legend', dimSegmentId, botRuleName, skipSharedReports=false) {
    const legendRsidList = require('./usefulInfo/Legend/botValidationRsidList.js');
    
    try {
        console.log(`\n🤖 Processing bot rule: ${botRuleName}`);
        console.log("Starting bot-specific requests concurrently...");
        
        // Only download bot-specific reports (not the shared ones)
        const requestPromises = BOT_SPECIFIC_REPORTS.map(reportName =>
            safeIterateRsidRequests(legendRsidList, fromDate, toDate, reportName, clientName, dimSegmentId, botRuleName)
        );
        
        // Optionally download shared reports if not skipping
        if (!skipSharedReports) {
            SHARED_REPORTS.forEach(reportName => {
                requestPromises.push(
                    safeIterateRsidRequests(legendRsidList, fromDate, toDate, reportName, clientName, undefined, botRuleName)
                );
            });
        }
        
        await Promise.all(requestPromises);
        
        console.log(`✓ All requests completed for bot rule: ${botRuleName}`);
    } catch (error) {
        console.error(`An error occurred processing bot rule ${botRuleName}: `, error);
        throw error;
    }
}

/**
 * Processes multiple bot rules with optimization for shared reports
 * Downloads shared reports once, then processes each bot rule individually
 */
async function processBotRules(botRulesList, fromDate, toDate, clientName='Legend', options = {}) {
    const { downloadShared = true, copyShared = true } = options;
    
    const legendRsidList = require('./usefulInfo/Legend/botValidationRsidList.js');
    
    console.log(`\n🚀 Starting optimized bot rule processing for ${botRulesList.length} rules`);
    console.log(`📅 Date range: ${fromDate} to ${toDate}`);
    
    try {
        // Step 1: Download shared reports once (if enabled)
        if (downloadShared && botRulesList.length > 0) {
            await downloadSharedBotValidationReports(legendRsidList, fromDate, toDate, clientName);
        }
        
        // Step 2: Process each bot rule
        for (let i = 0; i < botRulesList.length; i++) {
            const botRule = botRulesList[i];
            console.log(`\n[${i + 1}/${botRulesList.length}] Processing bot rule: ${botRule.botRuleName}`);
            
            // Download bot-specific reports (skip shared reports)
            await downloadBotRuleValidationData(
                fromDate, 
                toDate, 
                clientName, 
                botRule.dimSegmentId, 
                botRule.botRuleName,
                true // skipSharedReports = true
            );
            
            // Copy shared reports with this bot rule's name (if enabled)
            if (copyShared) {
                await copySharedReportsForBotRule(
                    legendRsidList,
                    fromDate,
                    toDate,
                    clientName,
                    botRule.botRuleName
                );
            }
        }
        
        console.log("\n🎉 All bot rules have been processed successfully!");
        
    } catch (error) {
        console.error("\n❌ Error in processBotRules:", error);
        throw error;
    }
}

// Export the functions for use as a module
module.exports = {
    downloadBotRuleValidationData,
    processBotRules,
    downloadSharedBotValidationReports,
    copySharedReportsForBotRule,
    SHARED_REPORTS,
    BOT_SPECIFIC_REPORTS
};

// Only run the example if this file is executed directly
if (require.main === module) {

    const readBotRulesFromCSV = require('./utils/readBotRulesFromCSV');

    botRulesFromFile = readBotRulesFromCSV('Oddspedia-AdHoc-Jan26-RoundFive_validate.csv','download') //update the file name as needed
    // Example usage:
    // const botRulesList = [
    //     {
    //         "dimSegmentId": "s3938_68875fcb762ef06cc5283857",
    //         "botRuleName": "0099SBR-SG-UserAgent"
    //     }
    // ];
    const botRulesList = botRulesFromFile

    processBotRules(botRulesList, '2024-02-01', '2026-02-01', 'Legend')
        .catch(console.error);
}