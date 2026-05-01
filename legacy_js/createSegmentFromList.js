/**
 * Adobe Segment Creation Script (Enhanced with Lookup Support)
 * 
 * Creates Adobe Analytics segments from a CSV file.
 * Supports single-condition and dual-condition (AND) segments.
 * Now includes automatic lookup for dimensions that require numeric IDs.
 * 
 * Usage:
 *   Normal mode: node createSegmentFromList.js <ListName>
 *   Test mode:   node createSegmentFromList.js <ListName> --test <rowNumber>
 */

const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const csv = require('csv-parser');
const { stringify } = require('csv-stringify/sync');
const getAdobeAccessToken = require('./utils/getAdobeAccessToken');
const retrieveLegendRsid = require('./utils/retrieveLegendRsid');
const searchLookupValue = require('./utils/LookupValueSearcher');
const shareAdobeSegment = require('./utils/shareAdobeSegment');

// ============================================================================
// CONFIGURATION - Easy to find and edit for future development
// ============================================================================

/**
 * Allowed dimension values in the CSV.
 * Add or remove values here to control which dimensions are accepted.
 */
const ALLOWED_DIMENSIONS = [
    'PageURL',
    'Page URL',
    'Domain',
    'UserAgent',
    'User Agent',
    'Region',
    'Regions',
    'OperatingSystem',
    'OperatingSystems',
    'Operating System',
    'Operating Systems',
    'MonitorResolution',
    'Monitor Resolution',
    'MobileManufacturer',
    'MarketingChannel',
    'Marketing Channel',
    'BrowserType',
    'Browser Type',
    'Referring Domain',
    'ReferringDomain'
];

/**
 * Mapping from friendly dimension names to Adobe Analytics dimension IDs.
 * Derived from clientLegend.yaml reportConfig section.
 */
const DIMENSION_MAPPING = {
    'PageURL': 'variables/evar2',
    'Page URL': 'variables/evar2',
    'Domain': 'variables/filtereddomain',
    'UserAgent': 'variables/evar23',
    'User Agent': 'variables/evar23',
    'Region': 'variables/georegion',
    'Regions': 'variables/georegion',
    'OperatingSystem': 'variables/operatingsystem',
    'OperatingSystems': 'variables/operatingsystem',
    'Operating System': 'variables/operatingsystem',
    'Operating Systems': 'variables/operatingsystem',
    'MonitorResolution': 'variables/monitorresolution',
    'Monitor Resolution': 'variables/monitorresolution',
    'MobileManufacturer': 'variables/mobilemanufacturer',
    'Mobile Manufacturer': 'variables/mobilemanufacturer',
    'MarketingChannel': 'variables/marketingchannel',
    'Marketing Channel': 'variables/marketingchannel',
    'BrowserType': 'variables/browsertype',
    'Browser Type': 'variables/browsertype',
    'Referring Domain': 'variables/referringdomain',
    'ReferringDomain': 'variables/referringdomain'
};

/**
 * Mapping from friendly dimension names to description text used in segment definitions.
 */
const DIMENSION_DESCRIPTIONS = {
    'PageURL': 'Page URL',
    'Page URL': 'Page URL',
    'Domain': 'Domain',
    'UserAgent': 'User Agent',
    'User Agent': 'User Agent',
    'Region': 'Region',
    'Regions': 'Region',
    'OperatingSystem': 'Operating Systems',
    'OperatingSystems': 'Operating Systems',
    'Operating System': 'Operating Systems',
    'Operating Systems': 'Operating Systems',
    'MonitorResolution': 'Monitor Resolution',
    'Monitor Resolution': 'Monitor Resolution',
    'MobileManufacturer': 'Mobile Manufacturer',
    'Mobile Manufacturer': 'Mobile Manufacturer',
    'MarketingChannel': 'Marketing Channel',
    'Marketing Channel': 'Marketing Channel',
    'BrowserType': 'Browser Type',
    'Browser Type': 'Browser Type',
    'Referring Domain': 'Referring Domain',
    'ReferringDomain': 'Referring Domain'
};

/**
 * Dimensions that require numeric IDs instead of string values.
 * These dimensions will use lookup files to convert strings to numeric IDs.
 */
const DIMENSIONS_REQUIRING_LOOKUP = [
    'BrowserType',
    'MonitorResolution',
    'Monitor Resolution',
    'MarketingChannel',
    'Marketing Channel',
    'Region',
    'Regions'
];

// File paths
const INPUT_BASE_PATH = './usefulInfo/Legend/segmentCreationLists';
const OUTPUT_COMPARE_PATH = './UsefulInfo/Legend/BotCompareLists';
const OUTPUT_VALIDATE_PATH = './UsefulInfo/Legend/BotRuleLists';
const TEST_OUTPUT_PATH = './usefulInfo/Legend/testOutput';

// Client name for Adobe API (adjust as needed)
const CLIENT_NAME = 'Legend';

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================



/**
 * Validates that a dimension value is in the allowed list.
 * @param {string} dimension - The dimension value to validate
 * @returns {boolean} - True if valid, false otherwise
 */
function isValidDimension(dimension) {
    if (!dimension || dimension.trim() === '') {
        return true; // Empty is valid (for optional Dimension2)
    }
    return ALLOWED_DIMENSIONS.includes(dimension.trim());
}

/**
 * Gets the Adobe dimension ID for a friendly dimension name.
 * @param {string} dimension - The friendly dimension name
 * @returns {string|null} - The Adobe dimension ID or null if not found
 */
function getAdobeDimensionId(dimension) {
    return DIMENSION_MAPPING[dimension.trim()] || null;
}

/**
 * Gets the description for a dimension.
 * @param {string} dimension - The friendly dimension name
 * @returns {string} - The description text
 */
function getDimensionDescription(dimension) {
    return DIMENSION_DESCRIPTIONS[dimension.trim()] || dimension;
}

/**
 * Checks if a dimension requires lookup (numeric ID instead of string).
 * @param {string} dimension - The friendly dimension name
 * @returns {boolean} - True if lookup is required
 */
function requiresLookup(dimension) {
    return DIMENSIONS_REQUIRING_LOOKUP.includes(dimension.trim());
}

/**
 * Reads a lookup file and returns a Map of string values to numeric IDs.
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
 * Normalizes monitor resolution format to include spaces around 'x' separator.
 * Example: "800x600" becomes "800 x 600", "1920 x 1080" stays "1920 x 1080"
 * @param {string} resolution - The resolution string
 * @returns {string} - Normalized resolution with spaces
 */
function normalizeMonitorResolution(resolution) {
    // Replace any occurrence of digits followed by 'x' followed by digits
    // with the same pattern but with spaces around the 'x'
    return resolution.replace(/(\d+)\s*x\s*(\d+)/gi, '$1 x $2');
}

/**
 * Gets the value to use in segment definition (performs lookup if needed).
 * @param {string} dimension - The friendly dimension name
 * @param {string} itemValue - The string value from CSV
 * @param {string} clientName - The client name
 * @returns {Promise<{value: string, isNumeric: boolean}>} - The value to use and whether it's numeric
 */
async function getSegmentValue(dimension, itemValue, clientName) {
    // Normalize monitor resolution format if applicable
    let processedValue = itemValue;
    if (dimension.includes('Monitor') || dimension.includes('Resolution')) {
        processedValue = normalizeMonitorResolution(itemValue);
    }
    
    // If this dimension doesn't require lookup, return the processed value as string
    if (!requiresLookup(dimension)) {
        return { value: processedValue, isNumeric: false };
    }
    
    // Get the Adobe dimension ID
    const adobeDimensionId = getAdobeDimensionId(dimension);
    if (!adobeDimensionId) {
        throw new Error(`No Adobe dimension ID found for: ${dimension}`);
    }
    
    // Build lookup file path
    const cleanDimensionName = adobeDimensionId.replace(/[^a-zA-Z0-9]/g, '');
    const lookupFilePath = path.join('usefulInfo', clientName, cleanDimensionName, 'lookup.txt');
    
    // Read the lookup file
    const lookupMap = readLookupFile(lookupFilePath);
    
    // Check if value exists in lookup (using processed value)
    if (lookupMap.has(processedValue)) {
        const numericId = lookupMap.get(processedValue);
        console.log(`    Lookup: "${processedValue}" -> ${numericId}`);
        return { value: numericId, isNumeric: true };
    }
    
    // Value not found in lookup file - search for it
    console.log(`    Lookup: "${processedValue}" not found in local file, searching...`);
    const numericId = await searchLookupValue(clientName, adobeDimensionId, processedValue);
    
    if (!numericId) {
        throw new Error(`Could not find numeric ID for "${processedValue}" in dimension ${dimension}`);
    }
    
    return { value: numericId, isNumeric: true };
}

/**
 * Ensures botRuleName is not longer than 95 characters by applying size reduction strategies.
 * Strategy order:
 * 1. Replace dimension names with abbreviated versions
 * 2. If still > 95, remove vowels from the 4th part (parts separated by underscores)
 * 3. If still > 95, truncate to 95 characters
 * 
 * @param {string} botRuleName - The bot rule name to potentially shorten
 * @returns {string} - The shortened bot rule name (max 95 characters)
 */
function ensureBotRuleNameLength(botRuleName) {
    // If already 95 or less, return as-is
    if (botRuleName.length <= 95) {
        return botRuleName;
    }
    
    console.log(`    BotRuleName length (${botRuleName.length}) exceeds 95, applying reductions...`);
    
    // Step 1: Replace dimension names with abbreviated versions
    let result = botRuleName;
    
    // Define abbreviation mapping - order matters! Longer patterns first to avoid partial replacements
    const abbreviations = [
        // Operating System variants (longest first)
        { pattern: /OperatingSystems/gi, replacement: 'OS' },
        { pattern: /OperatingSystem/gi, replacement: 'OS' },
        { pattern: /Operating Systems/gi, replacement: 'OS' },
        { pattern: /Operating System/gi, replacement: 'OS' },
        // Monitor Resolution variants
        { pattern: /MonitorResolution/gi, replacement: 'MonRes' },
        { pattern: /Monitor Resolution/gi, replacement: 'MonRes' },
        // Marketing Channel variants
        { pattern: /MarketingChannel/gi, replacement: 'MarCha' },
        { pattern: /Marketing Channel/gi, replacement: 'MarCha' },
        // Referring Domain variants
        { pattern: /ReferringDomain/gi, replacement: 'RefDom' },
        { pattern: /Referring Domain/gi, replacement: 'RefDom' },
        // Mobile Manufacturer variants
        { pattern: /MobileManufacturer/gi, replacement: 'MobMan' },
        { pattern: /Mobile Manufacturer/gi, replacement: 'MobMan' },
        // Browser Type variants
        { pattern: /BrowserType/gi, replacement: 'BrowType' },
        { pattern: /Browser Type/gi, replacement: 'BrowType' },
        // User Agent variants
        { pattern: /UserAgent/gi, replacement: 'UsAg' },
        { pattern: /User Agent/gi, replacement: 'UsAg' },
        // PageURL variants
        { pattern: /PageURL/gi, replacement: 'URL' },
        { pattern: /Page URL/gi, replacement: 'URL' },
        // Region variants (Regions before Region)
        { pattern: /Regions/gi, replacement: 'Reg' },
        { pattern: /Region/gi, replacement: 'Reg' },
        // Domain (must be after ReferringDomain)
        { pattern: /Domain/gi, replacement: 'Dom' }
    ];
    
    // Apply all abbreviations
    for (const abbr of abbreviations) {
        result = result.replace(abbr.pattern, abbr.replacement);
    }
    
    console.log(`    After abbreviations: length = ${result.length}`);
    
    // Check if we're done
    if (result.length <= 95) {
        return result;
    }
    
    // Step 2: Remove vowels from the 4th part (parts separated by underscores or hyphens)
    // Try underscores first, then hyphens
    let parts = result.split('_');
    
    if (parts.length >= 4) {
        // Remove vowels from 4th part (index 3)
        const originalPart = parts[3];
        parts[3] = parts[3].replace(/[aeiouAEIOU]/g, '');
        console.log(`    Removed vowels from 4th part: "${originalPart}" -> "${parts[3]}"`);
        result = parts.join('_');
    } else {
        // Try splitting by hyphens if no underscores or fewer than 4 parts
        parts = result.split('-');
        if (parts.length >= 4) {
            const originalPart = parts[3];
            parts[3] = parts[3].replace(/[aeiouAEIOU]/g, '');
            console.log(`    Removed vowels from 4th part: "${originalPart}" -> "${parts[3]}"`);
            result = parts.join('-');
        }
    }
    
    console.log(`    After vowel removal: length = ${result.length}`);
    
    // Check if we're done
    if (result.length <= 95) {
        return result;
    }
    
    // Step 3: Truncate to 95 characters
    console.log(`    Truncating to 95 characters`);
    return result.substring(0, 95);
}

/**
 * Transforms segment name to botRuleName format for Compare output.
 * - If contains "UserAgent=", removes everything after "UserAgent=" up until "AND" or end of string
 * - Strips spaces, colons, periods, slashes, and commas
 * - Ensures final length does not exceed 95 characters
 * @param {string} segmentName - The original segment name
 * @returns {string} - The transformed botRuleName
 */
function transformToBotRuleName(segmentName) {
    let result = segmentName;
    console.log('startingresult', result)
    
    // If contains "UserAgent = ", remove everything after it until "AND" or end of string
    if (result.includes('UserAgent = ')) {
        result = result.replace(/UserAgent = .*?(?=\s+AND\s+|$)/gi, 'UserAgent');
    }

    // If contains "UserAgent=", remove everything after it until "AND" or end of string
    if (result.includes('UserAgent=')) {
        result = result.replace(/UserAgent=.*?(?=\s+AND\s+|$)/gi, 'UserAgent');
    }
    
    // Strip spaces, colons, periods, slashes, hyphens, and commas
    result = result.replace(/[\s:./,-]/g, '');

    // Ensure length does not exceed 95 characters
    result = ensureBotRuleNameLength(result);

    return result;
}

/**
 * Transforms segment name to botRuleName format for Validate output.
 * Steps executed in order:
 * 1. Remove spaces
 * 2. Remove colons
 * 3. Remove hyphens
 * 4. If contains UserAgent=, remove everything after it until "AND" or end of string
 * 5. Remove slashes
 * 6. Remove commas
 * 7. Replace any other special characters with hyphens
 * 8. Ensure final length does not exceed 95 characters
 * @param {string} segmentName - The original segment name
 * @returns {string} - The transformed botRuleName for Validate
 */
function transformToValidateBotRuleName(segmentName) {
    let result = segmentName;
    
    // Step 1: Remove spaces
    result = result.replace(/\s+/g, '');
    
    // Step 2: Remove colons
    result = result.replace(/:/g, '');
    
    // Step 3: Remove hyphens
    result = result.replace(/-/g, '');
    
    // Step 4: If contains UserAgent= or User Agent =, remove everything after it until "AND" or end of string
    if (result.includes('UserAgent = ')) {
        result = result.replace(/UserAgent = .*?(?=\s+AND\s+|$)/gi, 'UserAgent');
    }
    if (result.includes('UserAgent=')) {
        result = result.replace(/UserAgent=.*?(?=\s+AND\s+|$)/gi, 'UserAgent');
    }
    
    // Step 5: Remove slashes
    result = result.replace(/\//g, '');
    
    // Step 6: Remove commas
    result = result.replace(/,/g, '');
    
    // Step 7: Replace any other special characters with hyphens
    // Keep alphanumeric, underscores (already placed), and replace everything else with hyphens
    result = result.replace(/[^a-zA-Z0-9_]/g, '-');
    
    // Step 8: Ensure length does not exceed 95 characters
    result = ensureBotRuleNameLength(result);
    
    return result;
}

/**
 * Builds a single-condition segment definition.
 * @param {string} segmentName - Name of the segment
 * @param {string} rsid - Report Suite ID
 * @param {string} dimension1 - First dimension friendly name
 * @param {string} dimension1Item - Value for first dimension (numeric ID if lookup was used)
 * @param {boolean} dimension1IsNumeric - Whether dimension1Item is a numeric ID
 * @returns {object} - Segment definition object
 */
function buildSingleConditionSegment(segmentName, rsid, dimension1, dimension1Item, dimension1IsNumeric = false) {
    const adobeDimension = getAdobeDimensionId(dimension1);
    const description = getDimensionDescription(dimension1);
    
    // Build predicate based on whether we're using numeric ID or string
    let pred;
    if (dimension1IsNumeric) {
        // Numeric ID - use 'eq' and 'num'
        pred = {
            val: {
                func: 'attr',
                name: adobeDimension
            },
            func: 'eq',
            num: parseInt(dimension1Item),
            description: description
        };
    } else {
        // String value - use 'streq' and 'str'
        pred = {
            str: dimension1Item,
            val: {
                func: 'attr',
                name: adobeDimension
            },
            description: description,
            func: 'streq'
        };
    }
    
    return {
        name: segmentName,
        description: '',
        definition: {
            container: {
                func: 'container',
                context: 'visits',
                pred: pred
            },
            func: 'segment',
            version: [1, 0, 0]
        },
        isPostShardId: true,
        rsid: rsid
    };
}

/**
 * Builds a dual-condition segment definition (AND logic).
 * @param {string} segmentName - Name of the segment
 * @param {string} rsid - Report Suite ID
 * @param {string} dimension1 - First dimension friendly name
 * @param {string} dimension1Item - Value for first dimension (numeric ID if lookup was used)
 * @param {boolean} dimension1IsNumeric - Whether dimension1Item is a numeric ID
 * @param {string} dimension2 - Second dimension friendly name
 * @param {string} dimension2Item - Value for second dimension (numeric ID if lookup was used)
 * @param {boolean} dimension2IsNumeric - Whether dimension2Item is a numeric ID
 * @returns {object} - Segment definition object
 */
function buildDualConditionSegment(segmentName, rsid, dimension1, dimension1Item, dimension1IsNumeric, dimension2, dimension2Item, dimension2IsNumeric) {
    const adobeDimension1 = getAdobeDimensionId(dimension1);
    const adobeDimension2 = getAdobeDimensionId(dimension2);
    const description1 = getDimensionDescription(dimension1);
    const description2 = getDimensionDescription(dimension2);
    
    // Build first predicate
    let pred1;
    if (dimension1IsNumeric) {
        pred1 = {
            val: {
                func: 'attr',
                name: adobeDimension1
            },
            func: 'eq',
            num: parseInt(dimension1Item),
            description: description1
        };
    } else {
        pred1 = {
            str: dimension1Item,
            val: {
                func: 'attr',
                name: adobeDimension1
            },
            description: description1,
            func: 'streq'
        };
    }
    
    // Build second predicate
    let pred2;
    if (dimension2IsNumeric) {
        pred2 = {
            val: {
                func: 'attr',
                name: adobeDimension2
            },
            func: 'eq',
            num: parseInt(dimension2Item),
            description: description2
        };
    } else {
        pred2 = {
            str: dimension2Item,
            val: {
                func: 'attr',
                name: adobeDimension2
            },
            description: description2,
            func: 'streq'
        };
    }
    
    return {
        name: segmentName,
        description: '',
        definition: {
            container: {
                func: 'container',
                context: 'visits',
                pred: {
                    func: 'container',
                    context: 'hits',
                    pred: {
                        func: 'and',
                        preds: [pred1, pred2]
                    }
                }
            },
            func: 'segment',
            version: [1, 0, 0]
        },
        isPostShardId: true,
        rsid: rsid
    };
}

/**
 * Creates a segment via the Adobe API.
 * @param {object} segmentDefinition - The segment definition object
 * @returns {Promise<object>} - Response from Adobe API with segment ID
 */
async function createSegmentViaApi(segmentDefinition) {
    try {
        const config = yaml.load(fs.readFileSync(`./config/client_configs/client${CLIENT_NAME}.yaml`, 'utf8'));
        const { adobeOrgID, globalCompanyID, clientID } = config.adobe || {};

        if (!adobeOrgID || !globalCompanyID || !clientID) {
            throw new Error('Missing required Adobe configuration');
        }

        const accessToken = await getAdobeAccessToken(CLIENT_NAME);
        if (!accessToken) {
            throw new Error('Failed to get access token');
        }

        const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/segments`;
        const headers = {
            'Accept': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
            'x-api-key': clientID,
            'x-proxy-global-company-id': globalCompanyID,
            'x-gw-ims-org-id': adobeOrgID,
        };

        const response = await axios.post(apiUrl, segmentDefinition, { headers });
        return response.data;
    } catch (error) {
        if (error.response) {
            throw new Error(`API Error ${error.response.status}: ${JSON.stringify(error.response.data)}`);
        }
        throw error;
    }
}

/**
 * Validates a CSV row.
 * @param {object} row - CSV row object
 * @param {number} rowNumber - Row number for error reporting
 * @returns {object} - Validation result with valid flag and errors array
 */
function validateRow(row, rowNumber) {
    const errors = [];
    
    // Check required fields
    if (!row.SegmentName || row.SegmentName.trim() === '') {
        errors.push(`Row ${rowNumber}: Missing SegmentName`);
    }
    if (!row.CompareValidate || row.CompareValidate.trim() === '') {
        errors.push(`Row ${rowNumber}: Missing CompareValidate`);
    }
    
    // Validate CompareValidate
    const validCompareValidateValues = ['Compare', 'Validate', 'Compare - Special', 'Validate - Special'];
    if (row.CompareValidate && !validCompareValidateValues.includes(row.CompareValidate.trim())) {
        errors.push(`Row ${rowNumber}: CompareValidate must be one of: ${validCompareValidateValues.join(', ')}`);
    }
    
    // Check if this is a special segment (no API creation needed)
    const compareValidateValue = row.CompareValidate ? row.CompareValidate.trim() : '';
    const isSpecial = compareValidateValue === 'Compare - Special' || compareValidateValue === 'Validate - Special';
    
    // Skip dimension validation for special segments since no API call will be made
    if (!isSpecial) {
        // These validations only apply to normal segments that will be created via API
        if (!row.RSIDCleanName || row.RSIDCleanName.trim() === '') {
            errors.push(`Row ${rowNumber}: Missing RSIDCleanName`);
        }
        if (!row.Dimension1 || row.Dimension1.trim() === '') {
            errors.push(`Row ${rowNumber}: Missing Dimension1`);
        }
        if (!row.Dimension1Item || row.Dimension1Item.trim() === '') {
            errors.push(`Row ${rowNumber}: Missing Dimension1Item`);
        }
        
        // Validate dimensions
        if (row.Dimension1 && !isValidDimension(row.Dimension1)) {
            errors.push(`Row ${rowNumber}: Invalid Dimension1 "${row.Dimension1}". Allowed: ${ALLOWED_DIMENSIONS.join(', ')}`);
        }
        if (row.Dimension2 && row.Dimension2.trim() !== '' && !isValidDimension(row.Dimension2)) {
            errors.push(`Row ${rowNumber}: Invalid Dimension2 "${row.Dimension2}". Allowed: ${ALLOWED_DIMENSIONS.join(', ')}`);
        }
        
        // If Dimension2 exists, Dimension2Item must also exist
        if (row.Dimension2 && row.Dimension2.trim() !== '' && (!row.Dimension2Item || row.Dimension2Item.trim() === '')) {
            errors.push(`Row ${rowNumber}: Dimension2 specified but Dimension2Item is missing`);
        }
    }
    
    return {
        valid: errors.length === 0,
        errors: errors
    };
}

/**
 * Reads a CSV file and returns rows as objects.
 * @param {string} filePath - Path to the CSV file
 * @returns {Promise<Array>} - Array of row objects
 */
function readCsvFile(filePath) {
    return new Promise((resolve, reject) => {
        const rows = [];
        fs.createReadStream(filePath)
            .pipe(csv())
            .on('data', (row) => rows.push(row))
            .on('end', () => resolve(rows))
            .on('error', (error) => reject(error));
    });
}

/**
 * Writes an array of objects to a CSV file.
 * @param {string} filePath - Path to write the CSV file
 * @param {Array} data - Array of objects to write
 */
function writeCsvFile(filePath, data) {
    const csvString = stringify(data, { header: true });
    fs.writeFileSync(filePath, csvString);
}

/**
 * Ensures a directory exists, creating it if necessary.
 * @param {string} dirPath - Directory path
 */
function ensureDirectoryExists(dirPath) {
    if (!fs.existsSync(dirPath)) {
        fs.mkdirSync(dirPath, { recursive: true });
    }
}

/**
 * Main execution function.
 * @param {string} listName - Name of the CSV file to process
 * @param {boolean} testMode - If true, only process one row and save to JSON
 * @param {number} testRow - Row number to test (1-indexed)
 * @param {Array<string>} userIds - Array of user IDs to share segments with
 */
async function main(listName, testMode = false, testRow = null, userIds = []) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`Adobe Segment Creation Script (Enhanced with Lookup Support)`);
    console.log(`List: ${listName}`);
    console.log(`Mode: ${testMode ? `TEST (Row ${testRow})` : 'PRODUCTION'}`);
    console.log(`${'='.repeat(60)}\n`);

    // Build input file path
    const inputFilePath = path.join(INPUT_BASE_PATH, `${listName}.csv`);
    
    // Check if input file exists
    if (!fs.existsSync(inputFilePath)) {
        console.error(`Error: Input file not found: ${inputFilePath}`);
        process.exit(1);
    }

    // Read CSV file
    console.log(`Reading CSV file: ${inputFilePath}`);
    let rows;
    try {
        rows = await readCsvFile(inputFilePath);
    } catch (error) {
        console.error(`Error reading CSV file: ${error.message}`);
        process.exit(1);
    }

    console.log(`Found ${rows.length} rows in CSV\n`);

    // Validate all rows first
    console.log('Validating rows...');
    const validationResults = rows.map((row, index) => validateRow(row, index + 1));
    const invalidRows = validationResults.filter(r => !r.valid);
    
    if (invalidRows.length > 0) {
        console.error('\nValidation errors found:');
        invalidRows.forEach(r => r.errors.forEach(e => console.error(`  - ${e}`)));
        console.error(`\n${invalidRows.length} rows have validation errors. Please fix and retry.`);
        process.exit(1);
    }
    console.log('All rows validated successfully.\n');

    // If test mode, only process the specified row
    if (testMode) {
        if (testRow < 1 || testRow > rows.length) {
            console.error(`Error: Test row ${testRow} is out of range. Valid range: 1-${rows.length}`);
            process.exit(1);
        }
        
        const row = rows[testRow - 1];
        console.log(`Test mode: Processing row ${testRow}`);
        console.log(`  SegmentName: ${row.SegmentName}`);
        console.log(`  RSIDCleanName: ${row.RSIDCleanName}`);
        console.log(`  Dimension1: ${row.Dimension1} = ${row.Dimension1Item}`);
        if (row.Dimension2 && row.Dimension2.trim() !== '') {
            console.log(`  Dimension2: ${row.Dimension2} = ${row.Dimension2Item}`);
        }

        // Get RSID (remove periods from RSIDCleanName)
        const cleanRSID = row.RSIDCleanName.trim().replace(/\./g, '');
        const rsid = await retrieveLegendRsid(cleanRSID);
        if (!rsid) {
            console.error(`Error: Could not retrieve RSID for ${row.RSIDCleanName}`);
            process.exit(1);
        }
        console.log(`  RSID: ${rsid}\n`);

        // Get segment values (with lookup if needed)
        console.log('  Resolving dimension values:');
        const dimension1Result = await getSegmentValue(row.Dimension1.trim(), row.Dimension1Item.trim(), CLIENT_NAME);
        
        let dimension2Result = null;
        if (row.Dimension2 && row.Dimension2.trim() !== '') {
            dimension2Result = await getSegmentValue(row.Dimension2.trim(), row.Dimension2Item.trim(), CLIENT_NAME);
        }

        // Build segment definition
        let segmentDefinition;
        if (dimension2Result !== null) {
            segmentDefinition = buildDualConditionSegment(
                row.SegmentName.trim(),
                rsid,
                row.Dimension1.trim(),
                dimension1Result.value,
                dimension1Result.isNumeric,
                row.Dimension2.trim(),
                dimension2Result.value,
                dimension2Result.isNumeric
            );
        } else {
            segmentDefinition = buildSingleConditionSegment(
                row.SegmentName.trim(),
                rsid,
                row.Dimension1.trim(),
                dimension1Result.value,
                dimension1Result.isNumeric
            );
        }

        // Save to JSON file
        ensureDirectoryExists(TEST_OUTPUT_PATH);
        const outputFileName = `test_segment_row_${testRow}.json`;
        const outputFilePath = path.join(TEST_OUTPUT_PATH, outputFileName);
        fs.writeFileSync(outputFilePath, JSON.stringify(segmentDefinition, null, 2));
        console.log(`\nTest output saved to: ${outputFilePath}`);
        return;
    }

// Production mode: Process all rows
const compareResults = [];
const validateResults = [];
let successCount = 0;
let errorCount = 0;
let specialCount = 0;

for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const rowNum = i + 1;
    
    console.log(`\nProcessing row ${rowNum}/${rows.length}: ${row.SegmentName}`);

    try {
        const compareValidateValue = row.CompareValidate.trim();
        const isSpecial = compareValidateValue === 'Compare - Special' || compareValidateValue === 'Validate - Special';
        
        // Handle special segments (no creation/sharing)
        if (isSpecial) {
            console.log(`  ℹ Special segment - skipping creation and sharing`);
            
            const resultObj = {
                DimSegmentId: 'UPDATE-SEGMENT-ID',
                botRuleName: compareValidateValue === 'Compare - Special'
                    ? transformToBotRuleName(row.SegmentName.trim())
                    : transformToValidateBotRuleName(row.SegmentName.trim()),
                reportToIgnore: row.Dimension1.trim()
            };

            // Add to appropriate list
            if (compareValidateValue === 'Compare - Special') {
                compareResults.push(resultObj);
            } else {
                validateResults.push(resultObj);
            }

            specialCount++;
            continue;
        }

        // Normal segment processing
        // Get RSID (remove periods from RSIDCleanName)
        const cleanRSID = row.RSIDCleanName.trim().replace(/\./g, '');
        const rsid = await retrieveLegendRsid(cleanRSID);
        if (!rsid) {
            throw new Error(`Could not retrieve RSID for ${row.RSIDCleanName}`);
        }
        console.log(`  RSID: ${rsid}`);

        // Get segment values (with lookup if needed)
        console.log('  Resolving dimension values:');
        const dimension1Result = await getSegmentValue(row.Dimension1.trim(), row.Dimension1Item.trim(), CLIENT_NAME);
        
        let dimension2Result = null;
        if (row.Dimension2 && row.Dimension2.trim() !== '') {
            dimension2Result = await getSegmentValue(row.Dimension2.trim(), row.Dimension2Item.trim(), CLIENT_NAME);
        }

        // Build segment definition
        let segmentDefinition;
        if (dimension2Result !== null) {
            segmentDefinition = buildDualConditionSegment(
                row.SegmentName.trim(),
                rsid,
                row.Dimension1.trim(),
                dimension1Result.value,
                dimension1Result.isNumeric,
                row.Dimension2.trim(),
                dimension2Result.value,
                dimension2Result.isNumeric
            );
        } else {
            segmentDefinition = buildSingleConditionSegment(
                row.SegmentName.trim(),
                rsid,
                row.Dimension1.trim(),
                dimension1Result.value,
                dimension1Result.isNumeric
            );
        }

        // Create segment via API
        const result = await createSegmentViaApi(segmentDefinition);
        console.log(`  ✓ Created segment: ${result.id}`);

        // Share segment with specified users
        if (userIds.length > 0) {
            console.log(`  Sharing segment with ${userIds.length} user(s)...`);
            for (const userId of userIds) {
                try {
                    await shareAdobeSegment(result.id, userId, CLIENT_NAME);
                } catch (error) {
                    console.error(`  ✗ Failed to share with user ${userId}: ${error.message}`);
                }
            }
        }

        // Build result object with appropriate botRuleName transformation
        const resultObj = {
            DimSegmentId: result.id,
            botRuleName: compareValidateValue === 'Compare' 
                ? transformToBotRuleName(row.SegmentName.trim())
                : transformToValidateBotRuleName(row.SegmentName.trim()),
            reportToIgnore: row.Dimension1.trim()
        };

        // Add to appropriate list
        if (compareValidateValue === 'Compare') {
            compareResults.push(resultObj);
        } else {
            validateResults.push(resultObj);
        }

        successCount++;
    } catch (error) {
        console.error(`  ✗ Error: ${error.message}`);
        errorCount++;
    }

    // Small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 100));
}

    // Write output files
    console.log(`\n${'='.repeat(60)}`);
    console.log('Writing output files...');

    if (compareResults.length > 0) {
        ensureDirectoryExists(OUTPUT_COMPARE_PATH);
        const compareOutputPath = path.join(OUTPUT_COMPARE_PATH, `${listName}_compare.csv`);
        writeCsvFile(compareOutputPath, compareResults);
        console.log(`  Compare results (${compareResults.length} segments): ${compareOutputPath}`);
    }

    if (validateResults.length > 0) {
        ensureDirectoryExists(OUTPUT_VALIDATE_PATH);
        const validateOutputPath = path.join(OUTPUT_VALIDATE_PATH, `${listName}_validate.csv`);
        writeCsvFile(validateOutputPath, validateResults);
        console.log(`  Validate results (${validateResults.length} segments): ${validateOutputPath}`);
    }
    // Summary
    console.log(`\n${'='.repeat(60)}`);
    console.log('Summary:');
    console.log(`  Total rows processed: ${rows.length}`);
    console.log(`  Successful: ${successCount}`);
    console.log(`  Special (skipped): ${specialCount}`);
    console.log(`  Errors: ${errorCount}`);
    console.log(`  Compare segments: ${compareResults.length}`);
    console.log(`  Validate segments: ${validateResults.length}`);
    console.log(`${'='.repeat(60)}\n`);
}

// ============================================================================
// MODULE EXPORT
// ============================================================================

/**
 * Creates Adobe segments from a CSV list.
 * 
 * @param {string} listName - Name of the CSV file (with or without .csv extension)
 * @param {object} options - Optional configuration
 * @param {boolean} options.testMode - If true, save request as JSON instead of calling API
 * @param {number} options.testRow - Row number to test (1-indexed, only used in test mode)
 * @returns {Promise<object>} - Results summary
 * 
 * @example
 * // Production mode - process all rows
 * const createSegmentFromList = require('./createSegmentFromList');
 * await createSegmentFromList('JunAug25RoundOne');
 * 
 * @example
 * // Test mode - save JSON for row 3
 * await createSegmentFromList('JunAug25RoundOne', { testMode: true, testRow: 3 });
 */
async function createSegmentFromList(listName, options = {}) {
    const { testMode = false, testRow = null, userIds = [] } = options;
    
    // Strip .csv extension if provided
    const cleanListName = listName.replace(/\.csv$/i, '');
    
    return main(cleanListName, testMode, testRow, userIds);
}

module.exports = createSegmentFromList;