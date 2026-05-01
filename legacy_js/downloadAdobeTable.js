// Enhanced downloadAdobeTable.js
const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');
const getAdobeTable = require('./utils/getAdobeTable');
const rateLimitManager = require('./utils/RateLimitManager');

async function downloadAdobeTable(fromDate, toDate, requestName, clientName, dimSegmentID = undefined, rsid = "default", fileNameExtra = undefined) {
    let readWriteConfig;
    try {
        readWriteConfig = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
    } catch (e) {
        console.error('Error loading read/write configuration:', e);
        throw e; // Throw instead of return - let caller handle
    }

    const { folder: baseFolder } = readWriteConfig.storage || {};
    if (!baseFolder) {
        console.error('Base folder is undefined in read/write configuration.');
        throw new Error('Base folder is undefined in read/write configuration.'); // Throw instead of return
    }

    if (!clientName) {
        console.error('Client name is undefined.');
        throw new Error('Client name is undefined.'); // Throw instead of return
    }

    try {
        // Create a descriptive request ID for logging
        const requestId = `${requestName}|${fromDate}-${toDate}|${rsid}${dimSegmentID ? `|DIMSEG${dimSegmentID}` : ''}`;
        
        // Use the rate limit manager to execute the request
        const responseData = await rateLimitManager.executeRequest(
            () => getAdobeTable(fromDate, toDate, requestName, clientName, dimSegmentID, rsid),
            3, // maxRetries
            requestId // Request identifier for logging
        );

        if (responseData) {
            const folderPath = path.join(baseFolder, clientName, 'JSON');
            if (!fs.existsSync(folderPath)) {
                fs.mkdirSync(folderPath, { recursive: true });
            }

            const fileNameExtraPart = fileNameExtra ? `_${fileNameExtra}` : '';
            const dimSegmentPart = dimSegmentID ? `DIMSEG${dimSegmentID}_` : '';
            const filename = path.join(folderPath, `${clientName}_${requestName}${fileNameExtraPart}_${dimSegmentPart}${fromDate}_${toDate}.json`);       

            fs.writeFileSync(filename, JSON.stringify(responseData, null, 2));
            console.log('✅ Saved:', filename);
            return responseData; // Return the data for success indication
        } else {
            console.error('❌ Failed to get Adobe table data');
            throw new Error('Failed to get Adobe table data'); // Throw instead of just logging
        }
    } catch (error) {
        console.error(`❌ Error in downloadAdobeTable for ${requestName} (${fromDate}-${toDate}):`, error.message);
        throw error; // Re-throw the error instead of swallowing it
    }
}

module.exports = downloadAdobeTable;