const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const iterateRsidRequests = require('./utils/iterateRsidRequests');
const concatenateCSVs = require('./utils/concatenateCSVs');
const rateLimitManager = require('./utils/RateLimitManager');
const investigationRsidList = require('./usefulInfo/Legend/botInvestigationMinThresholdVisits')
const Papa = require('papaparse');
const getExpandedSegmentDetails = require('./utils/getSegment');
const { createAdobeSegment } = require('./utils/createSegment');
const processJSONFiles = require('./processJSONFiles');

/**
 * GenerateCountrySegments - Runs country report for all Report Suites which meet the minimum investigation threshold
 * @param {number} minimumVisitsInvestigation - Minimum visits for country to justify a separate investigation. Recommended value = 100,000
 * @param {string} fromDate - Optional start date in 'YYYY-MM-DD' format. If not provided, uses 90 days before toDate or yesterday
* @param {string} toDate - Optional end date in 'YYYY-MM-DD' format. If not provided, uses yesterday's date
*/
async function BotInvestigationGenerateCountrySegments(
    minimumVisitsInvestigation = 100000,
        fromDate = null,
    toDate = null
) {
    console.log('Starting GenerateCountrySegments...');
    console.log(`Configuration:
    - Minimum Visits for Investigation: ${minimumVisitsInvestigation}`)

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
  
    // Step 2: Call iterateRsidRequests with improved error handling
        console.log('Step 2: Starting RSID requests...');
        
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
            fromDateStr = fromDate;
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
            
            toDateStr = toDate;
            todayStr = toDate;
        } else {
            // Use yesterday as toDate if not provided
            const today = new Date();
            toDateObj = new Date(today);
            toDateObj.setDate(today.getDate() - 1);
            
            toDateStr = toDateObj.toISOString().split('T')[0];
            todayStr = toDateObj.toISOString().split('T')[0];
        }
        
        // Calculate fromDate if not provided (90 days before toDate)
        if (!fromDate) {
            fromDateObj = new Date(toDateObj);
            fromDateObj.setDate(toDateObj.getDate() - 90);
            fromDateStr = fromDateObj.toISOString().split('T')[0];
        }

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
                investigationRsidList,
                fromDateStr,
                toDateStr,
                'SegmentsBuilderCountry50',
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


        // Step 2.5: Validate country segment downloads and retry missing files
        console.log('Step 2.5: Validating country segment downloads and retrying missing files...');
        
        const BIGCSValidateAndRetryMissingDownloads = require('./utils/BIGCSValidateAndRetryMissingDownloads');
        
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
        
        try {
            const validationResults = await BIGCSValidateAndRetryMissingDownloads(
                investigationRsidList,
                fromDateStr,
                toDateStr,
                runName,
                storageFolder
            );
            
            // Log validation summary
            console.log(`✅ Country segment download validation completed - ${validationResults.foundFiles.length}/${validationResults.totalExpected} files found`);
            
            // Optional: You could decide to stop processing if too many files are missing
            const successRate = (validationResults.foundFiles.length / validationResults.totalExpected) * 100;
            if (successRate < 70) { // Less than 70% success rate for country data
                console.log(`⚠️  Warning: Low success rate (${successRate.toFixed(1)}%) for country segment data. Consider investigating network issues.`);
            }
            
            // Log some insights about the data
            if (validationResults.foundFiles.length > 0) {
                const filesWithRows = validationResults.foundFiles.filter(f => typeof f.rowCount === 'number');
                if (filesWithRows.length > 0) {
                    const totalCountries = filesWithRows.reduce((sum, f) => sum + f.rowCount, 0);
                    const avgCountriesPerRsid = (totalCountries / filesWithRows.length).toFixed(1);
                    console.log(`📊 Average countries per RSID: ${avgCountriesPerRsid}`);
                }
            }
            
        } catch (error) {
            console.log(`⚠️  Country segment download validation completed with errors: ${error.message}`);
            // Continue processing with available files
        }

        // Step 3: Process JSON files and convert to CSV
        console.log('Step 3: Processing JSON files to CSV...');
        
        // Use storage folder from settings + client name
        const folderPath = path.join(storageFolder, 'Legend', 'JSON');
        console.log("folderpath", folderPath);
        const filePattern = new RegExp(`${runName}.*\\.json$`);
        console.log("filepattern", filePattern);
        
        try {
            await processJSONFiles(
                folderPath,
                filePattern,
                runName // Use runName as optional folder
            );
            console.log('JSON to CSV processing completed');
        } catch (error) {
            console.log(`⚠️  JSON processing completed with errors: ${error.message}`);
        }

        // Step 4: Concatenate CSV files
        console.log('Step 4: Concatenating CSV files...');
        
        const csvFolderPath = path.join(path.dirname(folderPath), 'CSV', runName);
        const csvFilePattern = `${runName}.*\\.csv$`;
        const outputFilePath = path.join(path.dirname(folderPath), 'CSV', 'BotInvestigationRsidCountryData',runName, `BotInvestigationCountryData${fromDateStr}_${toDateStr}.csv`)

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
        // Step 5: Process CSV file and manage segments
        console.log('Step 5: Processing CSV file and managing segments...');
        
        // Load country segment lookup
        let countrySegmentLookup;
        const lookupPath = './usefulInfo/Legend/countrySegmentLookup.js';
        try {
            delete require.cache[require.resolve(lookupPath)];
            countrySegmentLookup = require(lookupPath);
        } catch (error) {
            console.log('⚠️  Country segment lookup file not found, creating new one...');
            countrySegmentLookup = [];
        }
        
        // Read and parse CSV file
        let csvData;
        try {
            const csvContent = fs.readFileSync(outputFilePath, 'utf8');
            const parseResult = Papa.parse(csvContent, {
                header: true,
                skipEmptyLines: true,
                dynamicTyping: true
            });
            csvData = parseResult.data;
            console.log(`📊 Loaded ${csvData.length} rows from CSV`);
        } catch (error) {
            console.error('Error reading CSV file:', error);
            throw error;
        }
        
        // Filter rows with visits > threshold and deduplicate by RSID + id + geo_country
        const highVolumeCountries = csvData
            .filter(row => row.visits > minimumVisitsInvestigation)
            .reduce((acc, row) => {
                // Extract RSID from fileName
                const fileNameParts = row.fileName.split('_');
                const rsidCleanName = fileNameParts.length > 3 ? fileNameParts[3] : 'Unknown';
                
                // Create unique key with RSID included
                const key = `${rsidCleanName}_${row.id}_${row.geo_country}`;
                if (!acc.has(key)) {
                    acc.set(key, row);
                }
                return acc;
            }, new Map());
        
        console.log(`🔍 Found ${highVolumeCountries.size} high-volume RSID x country combinations`);
        
        // Process each high-volume RSID + country combination
        const segmentResults = [];
        let segmentLookupModified = false;
        
        for (const [key, row] of highVolumeCountries) {
            console.log(`Processing ${row.geo_country} (ID: ${row.id})`);
            
            // Check if segment already exists in lookup
            const existingSegment = countrySegmentLookup.find(seg => seg.DimValueId === row.id.toString());
            
            let segmentId = null;
            let segmentValid = false;
            
            if (existingSegment) {
                console.log(`  📋 Found existing segment: ${existingSegment.SegmentId}`);
                
                // Validate existing segment
                try {
                    await getExpandedSegmentDetails(existingSegment.SegmentId, 'Legend');
                    segmentValid = true;
                    segmentId = existingSegment.SegmentId;
                    console.log(`  ✅ Segment is valid`);
                } catch (error) {
                    console.log(`  ❌ Segment validation failed: ${error.message}`);
                    // Remove invalid segment from lookup
                    const index = countrySegmentLookup.findIndex(seg => seg.DimValueId === row.id.toString());
                    if (index > -1) {
                        countrySegmentLookup.splice(index, 1);
                        segmentLookupModified = true;
                        console.log(`  🗑️  Removed invalid segment from lookup`);
                    }
                }
            }
            
            // Create new segment if needed
            if (!segmentValid) {
                console.log(`  🏗️  Creating new segment for ${row.geo_country}`);
                try {
                    const newSegment = await createAdobeSegment(
                        'Legend',
                        'variables/geocountry',
                        row.id.toString(),
                        row.geo_country
                    );
                    
                    if (newSegment && newSegment.id) {
                        segmentId = newSegment.id;
                        
                        // Add to country segment lookup
                        const newLookupEntry = {
                            SegmentId: newSegment.id,
                            SegmentName: newSegment.name,
                            DimValueId: row.id.toString(),
                            DimValueName: row.geo_country
                        };
                        
                        countrySegmentLookup.push(newLookupEntry);
                        segmentLookupModified = true;
                        console.log(`  ✅ Created new segment: ${newSegment.id}`);
                    } else {
                        console.log(`  ❌ Failed to create segment for ${row.geo_country}`);
                    }
                } catch (error) {
                    console.log(`  ❌ Error creating segment: ${error.message}`);
                }
                
                // Add delay between segment creation requests
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
            
            // Extract RSID clean name from fileName
            const fileNameParts = row.fileName.split('_');
            const rsidCleanName = fileNameParts.length > 3 ? fileNameParts[3] : 'Unknown';
            
            // Add to results
            if (segmentId) {
                segmentResults.push({
                    rsidCleanName,
                    geocountry: row.geo_country,
                    segmentId,
                    visits: row.visits
                });
            }
        }
        
        // Update country segment lookup file if modified
        if (segmentLookupModified) {
            try {
                const lookupContent = `
const countrySegmentLookup = ${JSON.stringify(countrySegmentLookup, null, 2)}

module.exports = countrySegmentLookup`;
                
                fs.writeFileSync(lookupPath, lookupContent);
                console.log('📝 Updated country segment lookup file');
            } catch (error) {
                console.log(`⚠️  Error updating lookup file: ${error.message}`);
            }
        }
        
        // Step 6: Output results file
        console.log('Step 6: Creating results file...');
        
        const resultsContent = `// Generated on ${todayStr}
// Date range: ${fromDateStr} to ${toDateStr}

const botInvestigationRsidCountriesMinThreshold = ${JSON.stringify(segmentResults, null, 2)}

module.exports = botInvestigationRsidCountriesMinThreshold;`;
        
        const resultsPath = './usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js';
        try {
            fs.writeFileSync(resultsPath, resultsContent);
            console.log(`📄 Results file created: ${resultsPath}`);
            console.log(`📈 ${segmentResults.length} country-RSID combinations above threshold`);
        } catch (error) {
            console.log(`⚠️  Error creating results file: ${error.message}`);
        }

        console.log('🎉 GenerateCOuntrySegments completed!');

        // Restore original process.exit
        process.exit = originalExit;
        process.exit(0);

        return {
            runName,
            rsidCount: investigationRsidList.length,
            outputFile: outputFilePath,
            resultsFile: resultsPath,
            segmentResults: segmentResults.length,
            dateRange: {
                from: fromDateStr,
                to: toDateStr
            }
        };

    } catch (error) {
        console.error('💥 Error in BotInvestigationGenerateCountrySegments:', error);
        process.exit = originalExit; // Restore original exit
        throw error;
    }
}

module.exports = BotInvestigationGenerateCountrySegments;