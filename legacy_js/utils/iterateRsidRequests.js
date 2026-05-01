// iterateRsidRequests.js
// V3 of this script now uses iterateDateRequests instead of downloadAdobeTable
const iterateDateRequests = require('./iterateDateRequests.js');
const legendRsidLookup = './usefulInfo/Legend/legendReportSuites.txt'
const retrieveValue = require('./retrieveValue.js')

async function processBatch(batch, fromDate, toDate, requestName, clientName, dimSegmentID, fileNameExtra, interval = 'full', delay = 0) {
    const promises = batch.map(rsidName => {
        try {
            let rsid = retrieveValue(legendRsidLookup, rsidName, 'right')
            let fileNameExtraPlusRsidame = fileNameExtra + '_' + rsidName
            console.log("Processing: ", fileNameExtraPlusRsidame)
            return iterateDateRequests(delay, fromDate, toDate, requestName, clientName, interval, dimSegmentID, rsid, fileNameExtraPlusRsidame);
        } catch (error) {
            console.error(`Error downloading data for RSID ${rsidName}:`, error);
            return Promise.reject(error);
        }
    });

    await Promise.all(promises);
}

async function iterateRsidRequests(rsidNameList, fromDate, toDate, requestName, clientName, dimSegmentID = undefined, fileNameExtra, interval = 'full', delay = 0) {
    const batchSize = 12;
    const batchDelay = 8000;

    try {
        for (let i = 0; i < rsidNameList.length; i += batchSize) {
            const batch = rsidNameList.slice(i, i + batchSize);
            console.log(`Processing batch ${Math.floor(i/batchSize) + 1} of ${Math.ceil(rsidNameList.length/batchSize)}`);
            
            await processBatch(batch, fromDate, toDate, requestName, clientName, dimSegmentID, fileNameExtra, interval, delay);
            
            if (i + batchSize < rsidNameList.length) {
                console.log(`Waiting ${batchDelay}ms before next batch...`);
                await new Promise(resolve => setTimeout(resolve, batchDelay));
            }
        }
        
        console.log(`\n=== All RSID batches completed successfully ===`);
        console.log(`Processed ${rsidNameList.length} RSIDs across ${Math.ceil(rsidNameList.length/batchSize)} batches`);
        
    } catch (error) {
        console.error(`\n✗ Error in iterateRsidRequests:`, error);
        throw error;
    } finally {
        // Explicitly exit the process after all RSIDs have been processed
        console.log(`\n--- Exiting process to close rate limit manager ---`);
        process.exit(0);
    }
}

module.exports = iterateRsidRequests;