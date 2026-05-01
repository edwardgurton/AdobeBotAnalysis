/**
 * Example Usage - Lookup File Generator
 * 
 * This file demonstrates how to use the LookupFileGenerator
 * to create lookup tables for Adobe Analytics dimensions.
 */

const generateLookupFile = require('../utils/LookupFileGenerator');

generateLookupFile('variables/georegion', 'Legend')

// =============================================================================
// EXAMPLE 1: Generate lookup file for BrowserType dimension
// =============================================================================

async function example1_BrowserType() {
    console.log('EXAMPLE 1: Generating lookup file for BrowserType\n');
    
    try {
        const filePath = await generateLookupFile('variables/browsertype', 'Legend');
        console.log(`\nLookup file created at: ${filePath}`);
    } catch (error) {
        console.error('Error:', error.message);
    }
}


// =============================================================================
// EXAMPLE 2: Generate lookup file for Operating Systems
// =============================================================================

async function example2_OperatingSystems() {
    console.log('EXAMPLE 2: Generating lookup file for Operating Systems\n');
    
    try {
        const filePath = await generateLookupFile('variables/operatingsystem', 'Legend');
        console.log(`\nLookup file created at: ${filePath}`);
    } catch (error) {
        console.error('Error:', error.message);
    }
}

// =============================================================================
// EXAMPLE 3: Generate lookup file for Mobile Manufacturer
// =============================================================================

async function example3_MobileManufacturer() {
    console.log('EXAMPLE 3: Generating lookup file for Mobile Manufacturer\n');
    
    try {
        const filePath = await generateLookupFile('variables/mobilemanufacturer', 'Legend');
        console.log(`\nLookup file created at: ${filePath}`);
    } catch (error) {
        console.error('Error:', error.message);
    }
}

// =============================================================================
// Run the examples
// =============================================================================

async function runExamples() {
    // Uncomment the example you want to run
    
    //await example1_BrowserType();
    
     await example2_OperatingSystems();
    
     await example3_MobileManufacturer();
}

// Execute if run directly
if (require.main === module) {
    runExamples().catch(error => {
        console.error('Fatal error:', error);
        process.exit(1);
    });
}

module.exports = { example1_BrowserType, example2_OperatingSystems, example3_MobileManufacturer };
