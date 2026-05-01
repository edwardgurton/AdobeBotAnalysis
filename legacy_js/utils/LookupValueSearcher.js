/**
 * Lookup Value Searcher
 * 
 * Searches for missing lookup values across multiple RSIDs.
 * Updates the lookup file when new values are discovered.
 * 
 * @module LookupValueSearcher
 */

const fs = require('fs');
const path = require('path');
const getAdobeTable = require('./getAdobeTable');
const retrieveLegendRsid = require('./retrieveLegendRsid');
const rsidList = require('../usefulInfo/Legend/rsidList');

/**
 * Reads a lookup file and returns a Map of string values to numeric IDs
 * @param {string} lookupFilePath - Path to the lookup file
 * @returns {Map<string, string>} - Map of string values to numeric IDs
 */
function readLookupFile(lookupFilePath) {
    const lookupMap = new Map();
    
    if (!fs.existsSync(lookupFilePath)) {
        return lookupMap;
    }
    
    const content = fs.readFileSync(lookupFilePath, 'utf8');
    const lines = content.split('\n');
    
    for (const line of lines) {
        // Skip comments and empty lines
        if (line.trim().startsWith('//') || line.trim().startsWith('/*') || 
            line.trim().startsWith('*') || line.trim() === '') {
            continue;
        }
        
        // Parse the lookup pair
        const parts = line.split('|');
        if (parts.length === 2) {
            const stringValue = parts[0].trim();
            const numericId = parts[1].trim();
            lookupMap.set(stringValue, numericId);
        }
    }
    
    return lookupMap;
}

/**
 * Updates the lookup file with new values
 * @param {string} lookupFilePath - Path to the lookup file
 * @param {Array<{stringValue: string, numericId: string}>} newPairs - New lookup pairs to add
 * @param {string} dimensionName - Dimension name for the header
 * @param {string} clientName - Client name for the header
 */
function updateLookupFile(lookupFilePath, newPairs, dimensionName, clientName) {
    // Read existing content
    let existingContent = '';
    let existingPairs = [];
    
    if (fs.existsSync(lookupFilePath)) {
        existingContent = fs.readFileSync(lookupFilePath, 'utf8');
        const lines = existingContent.split('\n');
        
        // Extract existing pairs (skip header comments)
        let inHeader = true;
        for (const line of lines) {
            if (inHeader && (line.trim().startsWith('/*') || line.trim().startsWith('*') || 
                line.trim().startsWith('//') || line.trim() === '')) {
                continue;
            }
            inHeader = false;
            
            const parts = line.split('|');
            if (parts.length === 2) {
                existingPairs.push(line.trim());
            }
        }
    }
    
    // Add new pairs
    const allPairs = [...existingPairs];
    for (const pair of newPairs) {
        const pairStr = `${pair.stringValue}|${pair.numericId}`;
        if (!allPairs.includes(pairStr)) {
            allPairs.push(pairStr);
        }
    }
    
    // Sort pairs alphabetically by string value
    allPairs.sort((a, b) => {
        const aValue = a.split('|')[0];
        const bValue = b.split('|')[0];
        return aValue.localeCompare(bValue);
    });
    
    // Build new file content
    const lastUpdated = new Date().toISOString().split('T')[0];
    let fileContent = `/**
 * Lookup Table for ${dimensionName}
 * 
 * Maps string values to their numeric IDs for use in Adobe Analytics segments.
 * 
 * Client: ${clientName}
 * Last Updated: ${lastUpdated}
 * 
 * Format: stringValue|numericId
 */

`;
    
    for (const pair of allPairs) {
        fileContent += `${pair}\n`;
    }
    
    // Write the updated file
    fs.writeFileSync(lookupFilePath, fileContent, 'utf8');
}

/**
 * Searches for a lookup value across multiple RSIDs
 * 
 * @param {string} clientName - Client name (e.g., 'Legend')
 * @param {string} dimensionName - Adobe API dimension name (e.g., 'variables/browsertype')
 * @param {string} lookupString - The string value to search for
 * @returns {Promise<string|null>} - The numeric ID if found, null otherwise
 * 
 * @example
 * const searchLookupValue = require('./LookupValueSearcher');
 * const numericId = await searchLookupValue('Legend', 'variables/browsertype', 'Apple');
 */
async function searchLookupValue(clientName, dimensionName, lookupString) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`Lookup Value Searcher`);
    console.log(`Client: ${clientName}`);
    console.log(`Dimension: ${dimensionName}`);
    console.log(`Looking for: "${lookupString}"`);
    console.log(`${'='.repeat(60)}\n`);
    
    // Clean dimension name for file paths
    const cleanDimensionName = dimensionName.replace(/[^a-zA-Z0-9]/g, '');
    
    // Determine lookup file path
    const lookupFilePath = path.join('usefulInfo', clientName, cleanDimensionName, 'lookup.txt');
    
    // Read existing lookup file
    console.log('Reading existing lookup file...');
    const existingLookup = readLookupFile(lookupFilePath);
    
    // Check if value already exists
    if (existingLookup.has(lookupString)) {
        const numericId = existingLookup.get(lookupString);
        console.log(`✓ Value already in lookup table: ${lookupString} -> ${numericId}`);
        return numericId;
    }
    
    console.log(`Value not found in existing lookup. Searching across RSIDs...`);
    console.log(`Total RSIDs to check: ${rsidList.length}\n`);
    
    // Create request name for this search
    const requestName = `Lookup${cleanDimensionName}`;
    
    // Calculate date range (past 30 days - shorter range for faster searches)
    const toDate = new Date();
    const fromDate = new Date();
    fromDate.setDate(fromDate.getDate() - 30);
    
    const toDateStr = toDate.toISOString().split('T')[0];
    const fromDateStr = fromDate.toISOString().split('T')[0];
    
    let foundValue = null;
    const newPairs = [];
    
    // Iterate through RSIDs
    for (let i = 0; i < rsidList.length; i++) {
        const rsidCleanName = rsidList[i];
        console.log(`[${i + 1}/${rsidList.length}] Checking ${rsidCleanName}...`);
        
        try {
            // Get the actual RSID from the clean name
            // const rsid = retrieveLegendRsid(rsidCleanName);
            rsid = rsidCleanName
            if (!rsid) {
                console.log(`  ⚠ Could not retrieve RSID for ${rsidCleanName}, skipping`);
                continue;
            }
            
            // Fetch data from Adobe
            const response = await getAdobeTable(
                fromDateStr,
                toDateStr,
                requestName,
                clientName,
                undefined, // No dimension segment
                rsid
            );
            
            if (!response || !response.rows) {
                console.log(`  ⚠ No data returned for ${rsidCleanName}`);
                continue;
            }
            
            // Check all values in the response
            for (const row of response.rows) {
                const stringValue = row.value;
                const numericId = row.itemId;
                
                // Check if this is a new value we haven't seen before
                if (!existingLookup.has(stringValue)) {
                    newPairs.push({ stringValue, numericId });
                    existingLookup.set(stringValue, numericId);
                    
                    // Check if this is the value we're looking for
                    if (stringValue === lookupString) {
                        foundValue = numericId;
                        console.log(`  ✓ FOUND! ${stringValue} -> ${numericId}`);
                    }
                }
            }
            
            // If we found new pairs, update the lookup file
            if (newPairs.length > 0) {
                console.log(`  📝 Discovered ${newPairs.length} new value(s), updating lookup file`);
                updateLookupFile(lookupFilePath, newPairs, dimensionName, clientName);
                newPairs.length = 0; // Clear the array after updating
            }
            
            // If we found our target value, we can stop searching
            if (foundValue !== null) {
                console.log(`\n${'='.repeat(60)}`);
                console.log(`Success! Found "${lookupString}" -> ${foundValue}`);
                console.log(`${'='.repeat(60)}\n`);
                return foundValue;
            }
            
            // Small delay to avoid rate limiting
            await new Promise(resolve => setTimeout(resolve, 200));
            
        } catch (error) {
            console.log(`  ✗ Error fetching data: ${error.message}`);
            continue;
        }
    }
    
    // Value not found after searching all RSIDs
    console.log(`\n${'='.repeat(60)}`);
    console.log(`⚠ Value "${lookupString}" not found in any RSID`);
    console.log(`${'='.repeat(60)}\n`);
    
    return null;
}

module.exports = searchLookupValue;
