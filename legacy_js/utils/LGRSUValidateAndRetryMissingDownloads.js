/**
 * Validates that all expected files were downloaded and retries missing ones
 * @param {Array} rsidCleanNamesList - List of RSID clean names that should have been processed
 * @param {string} fromDateStr - Start date string
 * @param {string} toDateStr - End date string
 * @param {string} runName - The run name used for file naming
 * @param {string} storageFolder - Base storage folder path
 * @returns {Object} Validation results with summary
 */
async function validateAndRetryMissingDownloads(
    rsidCleanNamesList,
    fromDateStr,
    toDateStr,
    runName,
    storageFolder
) {
    console.log('🔍 Starting download validation...');
    
    const fs = require('fs');
    const path = require('path');
    const iterateRsidRequests = require('./iterateRsidRequests');
    const rateLimitManager = require('./RateLimitManager');
    
    // Define the expected file location pattern
    const jsonFolderPath = path.join(storageFolder, 'Legend', 'JSON');
    
    // Track validation results
    const validationResults = {
        totalExpected: rsidCleanNamesList.length,
        foundFiles: [],
        missingFiles: [],
        retryAttempted: [],
        retrySuccessful: [],
        retryFailed: []
    };
    
    // Check for each expected file
    console.log(`📋 Checking for ${rsidCleanNamesList.length} expected files...`);
    
    for (const rsidCleanName of rsidCleanNamesList) {
        // Expected filename pattern: toplineMetricsForRsidValidation_Legend_{runName}_{rsidCleanName}_{fromDate}_{toDate}.json
        const expectedFileName = `Legend_toplineMetricsForRsidValidation_${runName}_${rsidCleanName}_${fromDateStr}_${toDateStr}.json`;
        const expectedFilePath = path.join(jsonFolderPath, expectedFileName);
        
        if (fs.existsSync(expectedFilePath)) {
            // Check if file has content (not empty or corrupted)
            try {
                const fileStats = fs.statSync(expectedFilePath);
                if (fileStats.size > 0) {
                    // Try to parse JSON to ensure it's valid
                    const fileContent = fs.readFileSync(expectedFilePath, 'utf8');
                    JSON.parse(fileContent); // This will throw if invalid JSON
                    validationResults.foundFiles.push({
                        rsidCleanName,
                        fileName: expectedFileName,
                        size: fileStats.size
                    });
                } else {
                    // File exists but is empty
                    console.log(`⚠️  Found empty file: ${expectedFileName}`);
                    validationResults.missingFiles.push({
                        rsidCleanName,
                        fileName: expectedFileName,
                        reason: 'empty_file'
                    });
                }
            } catch (error) {
                // File exists but is corrupted/invalid JSON
                console.log(`⚠️  Found corrupted file: ${expectedFileName} - ${error.message}`);
                validationResults.missingFiles.push({
                    rsidCleanName,
                    fileName: expectedFileName,
                    reason: 'corrupted_file'
                });
            }
        } else {
            // File doesn't exist
            validationResults.missingFiles.push({
                rsidCleanName,
                fileName: expectedFileName,
                reason: 'file_not_found'
            });
        }
    }
    
    // Report initial validation results
    console.log(`✅ Found ${validationResults.foundFiles.length} valid files`);
    console.log(`❌ Missing ${validationResults.missingFiles.length} files`);
    
    if (validationResults.missingFiles.length > 0) {
        console.log('📝 Missing files breakdown:');
        const reasons = {};
        validationResults.missingFiles.forEach(file => {
            reasons[file.reason] = (reasons[file.reason] || 0) + 1;
        });
        Object.entries(reasons).forEach(([reason, count]) => {
            console.log(`   - ${reason}: ${count} files`);
        });
        
        // Attempt to retry missing files
        console.log('🔄 Starting retry process for missing files...');
        
        // Extract just the RSID clean names for retry
        const missingRsidNames = validationResults.missingFiles.map(file => file.rsidCleanName);
        
        // Monitor rate limit manager during retry
        const retryStatusMonitor = setInterval(() => {
            const status = rateLimitManager.getStatus();
            if (status.queueLength > 0 || status.activeRequests > 0 || status.isPaused) {
                console.log(`🔄 Retry Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}, Paused: ${status.isPaused ? 'YES until ' + status.pauseUntil : 'NO'}`);
            }
        }, 15000);
        
        try {
            console.log(`🚀 Retrying ${missingRsidNames.length} missing downloads...`);
            validationResults.retryAttempted = [...missingRsidNames];
            
            await iterateRsidRequests(
                missingRsidNames,
                fromDateStr,
                toDateStr,
                'toplineMetricsForRsidValidation',
                'Legend',
                undefined, // No dimSegmentId
                runName
            );
            
            console.log('✅ Retry requests completed');
        } catch (error) {
            console.log(`⚠️  Retry requests completed with some errors: ${error.message}`);
        } finally {
            clearInterval(retryStatusMonitor);
        }
        
        // Wait for retry requests to complete
        console.log('⏳ Waiting for retry requests to complete...');
        let retryWaitCount = 0;
        while (rateLimitManager.getStatus().activeRequests > 0 || rateLimitManager.getStatus().queueLength > 0) {
            const status = rateLimitManager.getStatus();
            console.log(`📈 Retry Waiting - Queue: ${status.queueLength}, Active: ${status.activeRequests}`);
            await new Promise(resolve => setTimeout(resolve, 2000));
            retryWaitCount++;
            if (retryWaitCount > 30) { // Max 60 seconds wait
                console.log('⏰ Max retry wait time reached, continuing...');
                break;
            }
        }
        
        // Re-validate after retry
        console.log('🔍 Re-validating after retry...');
        for (const rsidCleanName of missingRsidNames) {
            const expectedFileName = `toplineMetricsForRsidValidation_Legend_${runName}_${rsidCleanName}_${fromDateStr}_${toDateStr}.json`;
            const expectedFilePath = path.join(jsonFolderPath, expectedFileName);
            
            if (fs.existsSync(expectedFilePath)) {
                try {
                    const fileStats = fs.statSync(expectedFilePath);
                    if (fileStats.size > 0) {
                        const fileContent = fs.readFileSync(expectedFilePath, 'utf8');
                        JSON.parse(fileContent); // Validate JSON
                        validationResults.retrySuccessful.push({
                            rsidCleanName,
                            fileName: expectedFileName,
                            size: fileStats.size
                        });
                        // Remove from missing files and add to found files
                        const missingIndex = validationResults.missingFiles.findIndex(f => f.rsidCleanName === rsidCleanName);
                        if (missingIndex > -1) {
                            validationResults.missingFiles.splice(missingIndex, 1);
                            validationResults.foundFiles.push({
                                rsidCleanName,
                                fileName: expectedFileName,
                                size: fileStats.size
                            });
                        }
                    } else {
                        validationResults.retryFailed.push({
                            rsidCleanName,
                            fileName: expectedFileName,
                            reason: 'empty_file_after_retry'
                        });
                    }
                } catch (error) {
                    validationResults.retryFailed.push({
                        rsidCleanName,
                        fileName: expectedFileName,
                        reason: 'corrupted_file_after_retry'
                    });
                }
            } else {
                validationResults.retryFailed.push({
                    rsidCleanName,
                    fileName: expectedFileName,
                    reason: 'still_not_found_after_retry'
                });
            }
        }
    }
    
    // Final validation summary
    console.log('\n📊 VALIDATION SUMMARY:');
    console.log(`   Total Expected: ${validationResults.totalExpected}`);
    console.log(`   ✅ Successfully Downloaded: ${validationResults.foundFiles.length}`);
    console.log(`   ❌ Still Missing: ${validationResults.missingFiles.length}`);
    
    if (validationResults.retryAttempted.length > 0) {
        console.log(`   🔄 Retry Attempted: ${validationResults.retryAttempted.length}`);
        console.log(`   ✅ Retry Successful: ${validationResults.retrySuccessful.length}`);
        console.log(`   ❌ Retry Failed: ${validationResults.retryFailed.length}`);
    }
    
    // Calculate success rate
    const successRate = ((validationResults.foundFiles.length / validationResults.totalExpected) * 100).toFixed(1);
    console.log(`   📈 Success Rate: ${successRate}%`);
    
    // Log any remaining issues
    if (validationResults.missingFiles.length > 0) {
        console.log('\n⚠️  REMAINING MISSING FILES:');
        validationResults.missingFiles.forEach(file => {
            console.log(`   - ${file.rsidCleanName}: ${file.reason}`);
        });
        
        // Write missing files report
        const missingFilesReport = {
            timestamp: new Date().toISOString(),
            runName: runName,
            dateRange: `${fromDateStr} to ${toDateStr}`,
            totalExpected: validationResults.totalExpected,
            totalFound: validationResults.foundFiles.length,
            totalMissing: validationResults.missingFiles.length,
            successRate: successRate,
            missingFiles: validationResults.missingFiles,
            retryAttempted: validationResults.retryAttempted.length,
            retrySuccessful: validationResults.retrySuccessful.length,
            retryFailed: validationResults.retryFailed.length
        };
        
        const reportPath = `./reportSuiteChecks/MissingFiles_${runName}.json`;
        try {
            // Ensure directory exists
            const reportDir = path.dirname(reportPath);
            if (!fs.existsSync(reportDir)) {
                fs.mkdirSync(reportDir, { recursive: true });
            }
            
            fs.writeFileSync(reportPath, JSON.stringify(missingFilesReport, null, 2));
            console.log(`📝 Missing files report saved to: ${reportPath}`);
        } catch (error) {
            console.log(`⚠️  Could not save missing files report: ${error.message}`);
        }
    } else {
        console.log('\n🎉 All files successfully downloaded!');
    }
    
    return validationResults;
}

module.exports = validateAndRetryMissingDownloads;
