/**
 * Validates that all expected country segment files were downloaded and retries missing ones
 * @param {Array} investigationRsidList - List of RSID clean names that should have been processed
 * @param {string} fromDateStr - Start date string
 * @param {string} toDateStr - End date string
 * @param {string} runName - The run name used for file naming
 * @param {string} storageFolder - Base storage folder path
 * @returns {Object} Validation results with summary
 */
async function validateAndRetryMissingCountrySegments(
    investigationRsidList,
    fromDateStr,
    toDateStr,
    runName,
    storageFolder
) {
    console.log('🔍 Starting country segments download validation...');
    
    const fs = require('fs');
    const path = require('path');
    const iterateRsidRequests = require('./iterateRsidRequests');
    const rateLimitManager = require('./RateLimitManager');
    
    // Define the expected file location pattern
    const jsonFolderPath = path.join(storageFolder, 'Legend', 'JSON');
    
    // Track validation results
    const validationResults = {
        totalExpected: investigationRsidList.length,
        foundFiles: [],
        missingFiles: [],
        retryAttempted: [],
        retrySuccessful: [],
        retryFailed: []
    };
    
    // Check for each expected file
    console.log(`📋 Checking for ${investigationRsidList.length} expected country segment files...`);
    
    for (const rsidCleanName of investigationRsidList) {
        // Expected filename pattern: SegmentsBuilderCountry50_Legend_{runName}_{rsidCleanName}_{fromDate}_{toDate}.json
        const expectedFileName = `Legend_SegmentsBuilderCountry50_${runName}_${rsidCleanName}_${fromDateStr}_${toDateStr}.json`;
        const expectedFilePath = path.join(jsonFolderPath, expectedFileName);
        
        if (fs.existsSync(expectedFilePath)) {
            // Check if file has content and valid structure
            try {
                const fileStats = fs.statSync(expectedFilePath);
                if (fileStats.size > 0) {
                    // Try to parse JSON to ensure it's valid
                    const fileContent = fs.readFileSync(expectedFilePath, 'utf8');
                    const jsonData = JSON.parse(fileContent);
                    
                    // Additional validation for country segment files
                    // Check if it has the expected structure for country data
                    let hasValidStructure = false;
                    if (jsonData && (jsonData.rows || jsonData.reportSuite || jsonData.dimension)) {
                        hasValidStructure = true;
                    }
                    
                    if (hasValidStructure) {
                        validationResults.foundFiles.push({
                            rsidCleanName,
                            fileName: expectedFileName,
                            size: fileStats.size,
                            rowCount: jsonData.rows ? jsonData.rows.length : 'N/A'
                        });
                    } else {
                        console.log(`⚠️  Found file with invalid structure: ${expectedFileName}`);
                        validationResults.missingFiles.push({
                            rsidCleanName,
                            fileName: expectedFileName,
                            reason: 'invalid_structure'
                        });
                    }
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
    console.log(`✅ Found ${validationResults.foundFiles.length} valid country segment files`);
    console.log(`❌ Missing ${validationResults.missingFiles.length} files`);
    
    if (validationResults.missingFiles.length > 0) {
        console.log('📝 Missing country segment files breakdown:');
        const reasons = {};
        validationResults.missingFiles.forEach(file => {
            reasons[file.reason] = (reasons[file.reason] || 0) + 1;
        });
        Object.entries(reasons).forEach(([reason, count]) => {
            console.log(`   - ${reason}: ${count} files`);
        });
        
        // Show sample of missing files for debugging
        console.log('📋 Sample missing files:');
        validationResults.missingFiles.slice(0, 5).forEach(file => {
            console.log(`   - ${file.rsidCleanName}: ${file.reason}`);
        });
        if (validationResults.missingFiles.length > 5) {
            console.log(`   ... and ${validationResults.missingFiles.length - 5} more`);
        }
        
        // Attempt to retry missing files
        console.log('🔄 Starting retry process for missing country segment files...');
        
        // Extract just the RSID clean names for retry
        const missingRsidNames = validationResults.missingFiles.map(file => file.rsidCleanName);
        
        // Monitor rate limit manager during retry
        const retryStatusMonitor = setInterval(() => {
            const status = rateLimitManager.getStatus();
            if (status.queueLength > 0 || status.activeRequests > 0 || status.isPaused) {
                console.log(`🔄 Country Retry Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}, Paused: ${status.isPaused ? 'YES until ' + status.pauseUntil : 'NO'}`);
            }
        }, 15000);
        
        try {
            console.log(`🚀 Retrying ${missingRsidNames.length} missing country segment downloads...`);
            validationResults.retryAttempted = [...missingRsidNames];
            
            await iterateRsidRequests(
                missingRsidNames,
                fromDateStr,
                toDateStr,
                'SegmentsBuilderCountry50', // Country segments report type
                'Legend',
                undefined, // No dimSegmentId
                runName
            );
            
            console.log('✅ Country segment retry requests completed');
        } catch (error) {
            console.log(`⚠️  Country segment retry requests completed with some errors: ${error.message}`);
        } finally {
            clearInterval(retryStatusMonitor);
        }
        
        // Wait for retry requests to complete
        console.log('⏳ Waiting for country segment retry requests to complete...');
        let retryWaitCount = 0;
        while (rateLimitManager.getStatus().activeRequests > 0 || rateLimitManager.getStatus().queueLength > 0) {
            const status = rateLimitManager.getStatus();
            console.log(`📈 Country Retry Waiting - Queue: ${status.queueLength}, Active: ${status.activeRequests}`);
            await new Promise(resolve => setTimeout(resolve, 2000));
            retryWaitCount++;
            if (retryWaitCount > 30) { // Max 60 seconds wait
                console.log('⏰ Max country retry wait time reached, continuing...');
                break;
            }
        }
        
        // Re-validate after retry
        console.log('🔍 Re-validating country segment files after retry...');
        for (const rsidCleanName of missingRsidNames) {
            const expectedFileName = `Legend_SegmentsBuilderCountry50_${runName}_${rsidCleanName}_${fromDateStr}_${toDateStr}.json`;
            const expectedFilePath = path.join(jsonFolderPath, expectedFileName);
            
            if (fs.existsSync(expectedFilePath)) {
                try {
                    const fileStats = fs.statSync(expectedFilePath);
                    if (fileStats.size > 0) {
                        const fileContent = fs.readFileSync(expectedFilePath, 'utf8');
                        const jsonData = JSON.parse(fileContent);
                        
                        // Validate structure
                        let hasValidStructure = false;
                        if (jsonData && (jsonData.rows || jsonData.reportSuite || jsonData.dimension)) {
                            hasValidStructure = true;
                        }
                        
                        if (hasValidStructure) {
                            validationResults.retrySuccessful.push({
                                rsidCleanName,
                                fileName: expectedFileName,
                                size: fileStats.size,
                                rowCount: jsonData.rows ? jsonData.rows.length : 'N/A'
                            });
                            // Remove from missing files and add to found files
                            const missingIndex = validationResults.missingFiles.findIndex(f => f.rsidCleanName === rsidCleanName);
                            if (missingIndex > -1) {
                                validationResults.missingFiles.splice(missingIndex, 1);
                                validationResults.foundFiles.push({
                                    rsidCleanName,
                                    fileName: expectedFileName,
                                    size: fileStats.size,
                                    rowCount: jsonData.rows ? jsonData.rows.length : 'N/A'
                                });
                            }
                        } else {
                            validationResults.retryFailed.push({
                                rsidCleanName,
                                fileName: expectedFileName,
                                reason: 'invalid_structure_after_retry'
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
    console.log('\n📊 COUNTRY SEGMENTS VALIDATION SUMMARY:');
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
    
    // Show some statistics about the found files
    if (validationResults.foundFiles.length > 0) {
        const totalSize = validationResults.foundFiles.reduce((sum, file) => sum + file.size, 0);
        const avgSize = (totalSize / validationResults.foundFiles.length / 1024).toFixed(1); // KB
        console.log(`   📊 Average File Size: ${avgSize} KB`);
        
        // Count files with row data
        const filesWithRows = validationResults.foundFiles.filter(file => file.rowCount !== 'N/A');
        if (filesWithRows.length > 0) {
            const totalRows = filesWithRows.reduce((sum, file) => sum + (typeof file.rowCount === 'number' ? file.rowCount : 0), 0);
            const avgRows = (totalRows / filesWithRows.length).toFixed(1);
            console.log(`   📊 Average Rows per File: ${avgRows}`);
        }
    }
    
    // Log any remaining issues
    if (validationResults.missingFiles.length > 0) {
        console.log('\n⚠️  REMAINING MISSING COUNTRY SEGMENT FILES:');
        
        // Group by reason for cleaner output
        const groupedMissing = {};
        validationResults.missingFiles.forEach(file => {
            if (!groupedMissing[file.reason]) {
                groupedMissing[file.reason] = [];
            }
            groupedMissing[file.reason].push(file.rsidCleanName);
        });
        
        Object.entries(groupedMissing).forEach(([reason, rsids]) => {
            console.log(`   ${reason}: ${rsids.length} files`);
            // Show first few RSIDs for each reason
            if (rsids.length <= 3) {
                rsids.forEach(rsid => console.log(`     - ${rsid}`));
            } else {
                rsids.slice(0, 3).forEach(rsid => console.log(`     - ${rsid}`));
                console.log(`     ... and ${rsids.length - 3} more`);
            }
        });
        
        // Write missing files report
        const missingFilesReport = {
            timestamp: new Date().toISOString(),
            reportType: 'CountrySegments',
            runName: runName,
            dateRange: `${fromDateStr} to ${toDateStr}`,
            totalExpected: validationResults.totalExpected,
            totalFound: validationResults.foundFiles.length,
            totalMissing: validationResults.missingFiles.length,
            successRate: successRate,
            missingFilesByReason: groupedMissing,
            retryAttempted: validationResults.retryAttempted.length,
            retrySuccessful: validationResults.retrySuccessful.length,
            retryFailed: validationResults.retryFailed.length,
            detailedMissingFiles: validationResults.missingFiles
        };
        
        const reportPath = `./reportSuiteChecks/MissingCountrySegmentFiles_${runName}.json`;
        try {
            // Ensure directory exists
            const reportDir = path.dirname(reportPath);
            if (!fs.existsSync(reportDir)) {
                fs.mkdirSync(reportDir, { recursive: true });
            }
            
            fs.writeFileSync(reportPath, JSON.stringify(missingFilesReport, null, 2));
            console.log(`📝 Missing country segment files report saved to: ${reportPath}`);
        } catch (error) {
            console.log(`⚠️  Could not save missing files report: ${error.message}`);
        }
    } else {
        console.log('\n🎉 All country segment files successfully downloaded!');
    }
    
    // Additional insights for country segments
    if (validationResults.foundFiles.length > 0) {
        console.log('\n📈 COUNTRY SEGMENTS DATA INSIGHTS:');
        const filesWithRowData = validationResults.foundFiles.filter(f => typeof f.rowCount === 'number');
        if (filesWithRowData.length > 0) {
            const sortedByRows = filesWithRowData.sort((a, b) => b.rowCount - a.rowCount);
            console.log(`   🏆 Most countries: ${sortedByRows[0].rsidCleanName} (${sortedByRows[0].rowCount} countries)`);
            if (sortedByRows.length > 1) {
                console.log(`   📊 Least countries: ${sortedByRows[sortedByRows.length - 1].rsidCleanName} (${sortedByRows[sortedByRows.length - 1].rowCount} countries)`);
            }
        }
    }
    
    return validationResults;
}

module.exports = validateAndRetryMissingCountrySegments;
