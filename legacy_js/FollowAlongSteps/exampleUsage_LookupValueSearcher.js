/**
 * Example Usage - Lookup Value Searcher
 * 
 * This file demonstrates how to use the LookupValueSearcher
 * to find missing lookup values across RSIDs.
 */

const searchLookupValue = require('../LookupValueSearcher');

// =============================================================================
// EXAMPLE 1: Search for "Apple" in BrowserType dimension
// =============================================================================

async function example1_SearchApple() {
    console.log('EXAMPLE 1: Searching for "Apple" in BrowserType dimension\n');
    
    try {
        const numericId = await searchLookupValue('Legend', 'variables/browsertype', 'Apple');
        
        if (numericId) {
            console.log(`\nResult: Apple = ${numericId}`);
        } else {
            console.log('\nValue not found in any RSID');
        }
    } catch (error) {
        console.error('Error:', error.message);
    }
}

// =============================================================================
// EXAMPLE 2: Search for a specific operating system
// =============================================================================

async function example2_SearchWindows() {
    console.log('EXAMPLE 2: Searching for "Windows" in Operating Systems\n');
    
    try {
        const numericId = await searchLookupValue('Legend', 'variables/operatingsystem', 'Windows');
        
        if (numericId) {
            console.log(`\nResult: Windows = ${numericId}`);
        } else {
            console.log('\nValue not found in any RSID');
        }
    } catch (error) {
        console.error('Error:', error.message);
    }
}

// =============================================================================
// EXAMPLE 3: Search for a mobile manufacturer
// =============================================================================

async function example3_SearchSamsung() {
    console.log('EXAMPLE 3: Searching for "Samsung" in Mobile Manufacturer\n');
    
    try {
        const numericId = await searchLookupValue('Legend', 'variables/mobilemanufacturer', 'Samsung');
        
        if (numericId) {
            console.log(`\nResult: Samsung = ${numericId}`);
        } else {
            console.log('\nValue not found in any RSID');
        }
    } catch (error) {
        console.error('Error:', error.message);
    }
}

// =============================================================================
// EXAMPLE 4: Search for a value that might not exist
// =============================================================================

async function example4_SearchUnknown() {
    console.log('EXAMPLE 4: Searching for a potentially non-existent value\n');
    
    try {
        const numericId = await searchLookupValue('Legend', 'variables/browsertype', 'MyCustomBrowser');
        
        if (numericId) {
            console.log(`\nResult: MyCustomBrowser = ${numericId}`);
        } else {
            console.log('\nValue not found - this browser type does not exist in Adobe Analytics');
        }
    } catch (error) {
        console.error('Error:', error.message);
    }
}

// =============================================================================
// Run the examples
// =============================================================================

async function runExamples() {
    // Uncomment the example you want to run
    
    await example1_SearchApple();
    
     await example2_SearchWindows();
    
     await example3_SearchSamsung();
    
     await example4_SearchUnknown();
}

// Execute if run directly
if (require.main === module) {
    runExamples().catch(error => {
        console.error('Fatal error:', error);
        process.exit(1);
    });
}

module.exports = { 
    example1_SearchApple, 
    example2_SearchWindows, 
    example3_SearchSamsung, 
    example4_SearchUnknown 
};
