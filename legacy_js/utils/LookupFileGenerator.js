/**
 * Lookup File Generator
 * 
 * Generates lookup files mapping dimension string values to their numeric IDs.
 * These lookup files are used when creating Adobe Analytics segments.
 * 
 * @module LookupFileGenerator
 */

const fs = require('fs');
const path = require('path');
const addRequestDetails = require('./addRequestDetails');
const getAdobeTable = require('./getAdobeTable');

/**
 * Generates a lookup file for a given dimension
 * 
 * @param {string} dimensionName - Adobe API dimension name (e.g., 'variables/browsertype')
 * @param {string} clientName - Client name (e.g., 'Legend')
 * @returns {Promise<string>} - Path to the generated lookup file
 * 
 * @example
 * const generateLookupFile = require('./LookupFileGenerator');
 * await generateLookupFile('variables/browsertype', 'Legend');
 */
async function generateLookupFile(dimensionName, clientName) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`Lookup File Generator`);
    console.log(`Dimension: ${dimensionName}`);
    console.log(`Client: ${clientName}`);
    console.log(`${'='.repeat(60)}\n`);

    // Clean dimension name for file/request naming (remove slashes and special chars)
    const cleanDimensionName = dimensionName.replace(/[^a-zA-Z0-9]/g, '');
    
    // Create a unique request name
    const requestName = `Lookup_${cleanDimensionName}`;
    
    // Calculate date range (past 365 days)
    const toDate = new Date();
    const fromDate = new Date();
    fromDate.setDate(fromDate.getDate() - 365);
    
    const toDateStr = toDate.toISOString().split('T')[0];
    const fromDateStr = fromDate.toISOString().split('T')[0];
    
    console.log(`Date range: ${fromDateStr} to ${toDateStr}`);
    
    try {
        // Step 1: Add request details (creates the report configuration)
        console.log('\nStep 1: Creating report configuration...');
        addRequestDetails(
            clientName,
            requestName,
            dimensionName,
            [], // No segments
            50000, // No row limit
            null // No additional metrics (will get default: unique_visitors, visits)
        );
        console.log('✓ Report configuration created');
        
        // Step 2: Get the Adobe table data using coverscom RSID
        console.log('\nStep 2: Fetching data from Adobe Analytics...');
        const retrieveLegendRsid = require('./retrieveLegendRsid');
        const rsid = retrieveLegendRsid('coverscom'); // Clean RSID name
        const requestNameCleaned = requestName.replace(/[^a-zA-Z0-9]/g, '');
        console.log(`Requesting ${requestNameCleaned}. Using RSID: ${rsid}`)
        const response = await getAdobeTable(
            fromDateStr,
            toDateStr,
            requestNameCleaned,
            clientName,
            undefined, // No dimension segment
            rsid
        );
        console.log(response);
        
        if (!response || !response.rows) {
            throw new Error('Failed to retrieve data from Adobe Analytics');
        }
        
        console.log(`✓ Retrieved ${response.rows.length} dimension values`);
        
        // Step 3: Build lookup table from response
        console.log('\nStep 3: Building lookup table...');
        const lookupPairs = [];
        
        for (const row of response.rows) {
            const stringValue = row.value; // The display name (e.g., "Apple")
            const numericId = row.itemId; // The numeric ID (e.g., "6")
            
            lookupPairs.push({ stringValue, numericId });
        }
        
        console.log(`✓ Built ${lookupPairs.length} lookup pairs`);
        
        // Step 4: Create the lookup file
        console.log('\nStep 4: Writing lookup file...');
        const outputDir = path.join('usefulInfo', clientName, cleanDimensionName);
        
        // Create directory if it doesn't exist
        if (!fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir, { recursive: true });
        }
        
        // Build file content with header comments
        const lastUpdated = new Date().toISOString().split('T')[0];
        let fileContent = `/**
 * Lookup Table for ${dimensionName}
 * 
 * Maps string values to their numeric IDs for use in Adobe Analytics segments.
 * 
 * Client: ${clientName}
 * RSID: ${rsid}
 * Date Range: ${fromDateStr} to ${toDateStr}
 * Last Updated: ${lastUpdated}
 * 
 * Format: stringValue|numericId
 */

`;
        
        // Add each lookup pair
        for (const pair of lookupPairs) {
            fileContent += `${pair.stringValue}|${pair.numericId}\n`;
        }
        
        // Write the file
        const outputFilePath = path.join(outputDir, 'lookup.txt');
        fs.writeFileSync(outputFilePath, fileContent, 'utf8');
        
        console.log(`✓ Lookup file saved: ${outputFilePath}`);
        console.log(`\n${'='.repeat(60)}`);
        console.log('Lookup file generation complete!');
        console.log(`${'='.repeat(60)}\n`);
        
        return outputFilePath;
        
    } catch (error) {
        console.error(`\n✗ Error generating lookup file: ${error.message}`);
        throw error;
    }
}

module.exports = generateLookupFile;
