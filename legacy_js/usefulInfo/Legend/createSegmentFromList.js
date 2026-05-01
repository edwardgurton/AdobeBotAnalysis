/**
 * Adobe Segment Creation Script
 * 
 * Creates Adobe Analytics segments from a CSV file.
 * Supports single-condition and dual-condition (AND) segments.
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
const getAdobeAccessToken = require('./getAdobeAccessToken');
const { retrieveLegendRsid } = require('./utils/retrieveLegendRsid');

// ============================================================================
// CONFIGURATION - Easy to find and edit for future development
// ============================================================================

/**
 * Allowed dimension values in the CSV.
 * Add or remove values here to control which dimensions are accepted.
 */
const ALLOWED_DIMENSIONS = [
    'PageURL',
    'Domain',
    'UserAgent',
    'OperatingSystems',
    'MonitorResolution',
    'MobileManufacturer',
    'BrowserType'
];

/**
 * Mapping from friendly dimension names to Adobe Analytics dimension IDs.
 * Derived from clientLegend.yaml reportConfig section.
 */
const DIMENSION_MAPPING = {
    'PageURL': 'variables/evar2',
    'Domain': 'variables/filtereddomain',
    'UserAgent': 'variables/evar23',
    'OperatingSystems': 'variables/operatingsystem',
    'MonitorResolution': 'variables/monitorresolution',
    'MobileManufacturer': 'variables/mobilemanufacturer',
    'BrowserType': 'variables/browsertype'
};

/**
 * Mapping from friendly dimension names to description text used in segment definitions.
 */
const DIMENSION_DESCRIPTIONS = {
    'PageURL': 'Page URL',
    'Domain': 'Domain',
    'UserAgent': 'User Agent',
    'OperatingSystems': 'Operating Systems',
    'MonitorResolution': 'Monitor Resolution',
    'MobileManufacturer': 'Mobile Manufacturer',
    'BrowserType': 'Browser Type'
};

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
 * Transforms segment name to botRuleName format.
 * - Strips spaces, colons, and periods
 * - If contains "UserAgent", strips the section after "UserAgent="
 * @param {string} segmentName - The original segment name
 * @returns {string} - The transformed botRuleName
 */
function transformToBotRuleName(segmentName) {
    let result = segmentName;
    
    // If contains "UserAgent", strip the section after "UserAgent="
    if (result.includes('UserAgent')) {
        // Find the position of "UserAgent=" and strip everything after it until next space or end
        const userAgentMatch = result.match(/UserAgent\s*=\s*[^\s,]+/i);
        if (userAgentMatch) {
            result = result.replace(userAgentMatch[0], 'UserAgent');
        }
    }
    
    // Strip spaces, colons, and periods
    result = result.replace(/[\s:.]/g, '');
    
    return result;
}

/**
 * Builds a single-condition segment definition.
 * @param {string} segmentName - Name of the segment
 * @param {string} rsid - Report Suite ID
 * @param {string} dimension1 - First dimension friendly name
 * @param {string} dimension1Item - Value for first dimension
 * @returns {object} - Segment definition object
 */
function buildSingleConditionSegment(segmentName, rsid, dimension1, dimension1Item) {
    const adobeDimension = getAdobeDimensionId(dimension1);
    const description = getDimensionDescription(dimension1);
    
    return {
        name: segmentName,
        description: '',
        definition: {
            container: {
                func: 'container',
                context: 'visits',
                pred: {
                    str: dimension1Item,
                    val: {
                        func: 'attr',
                        name: adobeDimension
                    },
                    description: description,
                    func: 'streq'
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
 * Builds a dual-condition segment definition (AND logic).
 * @param {string} segmentName - Name of the segment
 * @param {string} rsid - Report Suite ID
 * @param {string} dimension1 - First dimension friendly name
 * @param {string} dimension1Item - Value for first dimension
 * @param {string} dimension2 - Second dimension friendly name
 * @param {string} dimension2Item - Value for second dimension
 * @returns {object} - Segment definition object
 */
function buildDualConditionSegment(segmentName, rsid, dimension1, dimension1Item, dimension2, dimension2Item) {
    const adobeDimension1 = getAdobeDimensionId(dimension1);
    const adobeDimension2 = getAdobeDimensionId(dimension2);
    const description1 = getDimensionDescription(dimension1);
    const description2 = getDimensionDescription(dimension2);
    
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
                        preds: [
                            {
                                str: dimension1Item,
                                val: {
                                    func: 'attr',
                                    name: adobeDimension1
                                },
                                description: description1,
                                func: 'streq'
                            },
                            {
                                str: dimension2Item,
                                val: {
                                    func: 'attr',
                                    name: adobeDimension2
                                },
                                description: description2,
                                func: 'streq'
                            }
                        ]
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
 * Reads and parses the CSV file.
 * @param {string} filePath - Path to the CSV file
 * @returns {Promise<Array>} - Array of row objects
 */
function readCsvFile(filePath) {
    return new Promise((resolve, reject) => {
        const results = [];
        fs.createReadStream(filePath)
            .pipe(csv())
            .on('data', (data) => results.push(data))
            .on('end', () => resolve(results))
            .on('error', (error) => reject(error));
    });
}

/**
 * Validates a row from the CSV.
 * @param {object} row - The row object
 * @param {number} rowIndex - The row index (for error messages)
 * @returns {object} - { valid: boolean, errors: string[] }
 */
function validateRow(row, rowIndex) {
    const errors = [];
    
    // Check CompareValidate
    if (!row.CompareValidate || !['Compare', 'Validate'].includes(row.CompareValidate.trim())) {
        errors.push(`Row ${rowIndex}: CompareValidate must be 'Compare' or 'Validate'`);
    }
    
    // Check SegmentName
    if (!row.SegmentName || row.SegmentName.trim() === '') {
        errors.push(`Row ${rowIndex}: SegmentName is required`);
    }
    
    // Check RSIDCleanName
    if (!row.RSIDCleanName || row.RSIDCleanName.trim() === '') {
        errors.push(`Row ${rowIndex}: RSIDCleanName is required`);
    }
    
    // Check Dimension1
    if (!row.Dimension1 || row.Dimension1.trim() === '') {
        errors.push(`Row ${rowIndex}: Dimension1 is required`);
    } else if (!isValidDimension(row.Dimension1)) {
        errors.push(`Row ${rowIndex}: Invalid Dimension1 value '${row.Dimension1}'. Allowed values: ${ALLOWED_DIMENSIONS.join(', ')}`);
    }
    
    // Check Dimension1Item
    if (!row.Dimension1Item || row.Dimension1Item.trim() === '') {
        errors.push(`Row ${rowIndex}: Dimension1Item is required`);
    }
    
    // Check Dimension2 (optional, but must be valid if provided)
    if (row.Dimension2 && row.Dimension2.trim() !== '') {
        if (!isValidDimension(row.Dimension2)) {
            errors.push(`Row ${rowIndex}: Invalid Dimension2 value '${row.Dimension2}'. Allowed values: ${ALLOWED_DIMENSIONS.join(', ')}`);
        }
        // If Dimension2 is provided, Dimension2Item must also be provided
        if (!row.Dimension2Item || row.Dimension2Item.trim() === '') {
            errors.push(`Row ${rowIndex}: Dimension2Item is required when Dimension2 is provided`);
        }
    }
    
    return {
        valid: errors.length === 0,
        errors
    };
}

/**
 * Creates a segment via Adobe API.
 * @param {object} segmentDefinition - The segment definition object
 * @returns {Promise<object>} - The created segment response
 */
async function createSegmentViaApi(segmentDefinition) {
    // Load client configuration
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${CLIENT_NAME}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        throw new Error('Failed to load client configuration');
    }

    const { adobeOrgID, globalCompanyID, clientID } = config.adobe || {};
    if (!adobeOrgID || !globalCompanyID || !clientID) {
        throw new Error('Missing required Adobe configuration');
    }

    // Get access token
    const accessToken = await getAdobeAccessToken(CLIENT_NAME);
    if (!accessToken) {
        throw new Error('Failed to get access token');
    }

    // Set up request headers
    const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/segments`;
    const headers = {
        'Accept': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'x-api-key': clientID,
        'x-proxy-global-company-id': globalCompanyID,
        'x-gw-ims-org-id': adobeOrgID,
    };

    // Send request to create segment
    const response = await axios.post(apiUrl, segmentDefinition, { headers });

    if (response.status === 200 || response.status === 201) {
        return response.data;
    } else {
        throw new Error(`Failed to create segment. Status: ${response.status}`);
    }
}

/**
 * Ensures a directory exists, creating it if necessary.
 * @param {string} dirPath - The directory path
 */
function ensureDirectoryExists(dirPath) {
    if (!fs.existsSync(dirPath)) {
        fs.mkdirSync(dirPath, { recursive: true });
    }
}

/**
 * Writes results to CSV file.
 * @param {string} filePath - Output file path
 * @param {Array} data - Array of result objects
 */
function writeCsvFile(filePath, data) {
    const csvContent = stringify(data, {
        header: true,
        columns: ['DimSegmentId', 'botRuleName', 'reportToIgnore']
    });
    fs.writeFileSync(filePath, csvContent);
}

// ============================================================================
// MAIN FUNCTION
// ============================================================================

/**
 * Main function to process the CSV and create segments.
 * @param {string} listName - Name of the CSV file (without extension)
 * @param {boolean} testMode - If true, save request as JSON instead of calling API
 * @param {number} testRow - Row number to test (1-indexed, only used in test mode)
 */
async function main(listName, testMode = false, testRow = null) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`Adobe Segment Creation Script`);
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

        // Get RSID
        const rsid = await retrieveLegendRsid(row.RSIDCleanName.trim());
        if (!rsid) {
            console.error(`Error: Could not retrieve RSID for ${row.RSIDCleanName}`);
            process.exit(1);
        }
        console.log(`  RSID: ${rsid}`);

        // Build segment definition
        let segmentDefinition;
        if (row.Dimension2 && row.Dimension2.trim() !== '') {
            segmentDefinition = buildDualConditionSegment(
                row.SegmentName.trim(),
                rsid,
                row.Dimension1.trim(),
                row.Dimension1Item.trim(),
                row.Dimension2.trim(),
                row.Dimension2Item.trim()
            );
        } else {
            segmentDefinition = buildSingleConditionSegment(
                row.SegmentName.trim(),
                rsid,
                row.Dimension1.trim(),
                row.Dimension1Item.trim()
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

    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const rowNum = i + 1;
        
        console.log(`Processing row ${rowNum}/${rows.length}: ${row.SegmentName}`);

        try {
            // Get RSID
            const rsid = await retrieveLegendRsid(row.RSIDCleanName.trim());
            if (!rsid) {
                throw new Error(`Could not retrieve RSID for ${row.RSIDCleanName}`);
            }

            // Build segment definition
            let segmentDefinition;
            if (row.Dimension2 && row.Dimension2.trim() !== '') {
                segmentDefinition = buildDualConditionSegment(
                    row.SegmentName.trim(),
                    rsid,
                    row.Dimension1.trim(),
                    row.Dimension1Item.trim(),
                    row.Dimension2.trim(),
                    row.Dimension2Item.trim()
                );
            } else {
                segmentDefinition = buildSingleConditionSegment(
                    row.SegmentName.trim(),
                    rsid,
                    row.Dimension1.trim(),
                    row.Dimension1Item.trim()
                );
            }

            // Create segment via API
            const result = await createSegmentViaApi(segmentDefinition);
            console.log(`  ✓ Created segment: ${result.id}`);

            // Build result object
            const resultObj = {
                DimSegmentId: result.id,
                botRuleName: transformToBotRuleName(row.SegmentName.trim()),
                reportToIgnore: row.Dimension1.trim()
            };

            // Add to appropriate list
            if (row.CompareValidate.trim() === 'Compare') {
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
    const { testMode = false, testRow = null } = options;
    
    // Strip .csv extension if provided
    const cleanListName = listName.replace(/\.csv$/i, '');
    
    return main(cleanListName, testMode, testRow);
}

module.exports = createSegmentFromList;
