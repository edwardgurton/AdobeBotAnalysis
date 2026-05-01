const processJSONFilesLegendFinalBotRuleMetrics = require('./processJSONFilesLegendFinalBotRuleMetrics');
const concatenateCSVs = require('./utils/concatenateCSVs');
const getJsonStorageFolderPath = require('./utils/getJsonStorageFolderPath');
const getCsvStorageFolderPath = require('./utils/getCsvStorageFolderPath');
const path = require('path');

/**
 * Process an individual string for bot validation, transformation, and concatenation
 * @param {string} clientName - Name of the client
 * @param {string} processingString - String pattern to process
 */
async function processString(clientName, processingString) {
  try {
    console.log(`\n=== Starting Bot Validation Process ===`);
    console.log(`Client: ${clientName}`);
    console.log(`Processing String: ${processingString}`);

    // Get folder paths using utility functions
    const jsonFolderPath = getJsonStorageFolderPath(clientName);
    const csvBaseFolderPath = getCsvStorageFolderPath(clientName);

    console.log(`JSON Source Folder: ${jsonFolderPath}`);
    console.log(`CSV Base Folder: ${csvBaseFolderPath}`);

    // Create regex pattern for JSON file matching
    const jsonPattern = new RegExp(`.*${processingString}.*.json$`);
    console.log(`JSON Pattern: ${jsonPattern}`);

    // Define CSV paths
    const outputFolderPath = path.join(csvBaseFolderPath, processingString);
    const concatFilePattern = `${processingString}.*\\.csv`;
    const outputFilePath = path.join(csvBaseFolderPath, 'FinalBotRuleMetrics', `${processingString}.csv`);

    console.log(`CSV Output Folder: ${outputFolderPath}`);
    console.log(`CSV Concat Pattern: ${concatFilePattern}`);
    console.log(`Final Output File: ${outputFilePath}`);

    // Step 1: Process JSON files and wait for completion
    console.log(`\n--- Step 1: Processing JSON Files ---`);
    await processJSONFilesLegendFinalBotRuleMetrics(jsonFolderPath, jsonPattern, processingString);
    console.log(`✓ JSON processing completed for ${processingString}`);

    // Step 2: Concatenate CSV files
    console.log(`\n--- Step 2: Concatenating CSV Files ---`);
    await concatenateCSVs(outputFolderPath, concatFilePattern, outputFilePath);
    console.log(`✓ CSV concatenation completed for ${processingString}`);

    console.log(`\n=== Final Bot Rule Metrics Process Complete for ${processingString} ===\n`);

  } catch (error) {
    console.error(`\n❌ Error processing ${processingString}:`, error.message);
    throw error;
  }
}

/**
 * Main processing function for bot validation, transformation, and concatenation
 * @param {string} clientName - Name of the client
 * @param {string[]} processingStrings - Array of string patterns to process
 */
async function finalBotRuleMetricsTransformConcat(clientName, processingStrings) {
  console.log(`\n🚀 Starting batch processing for client: ${clientName}`);
  console.log(`Total strings to process: ${processingStrings.length}`);

  for (let i = 0; i < processingStrings.length; i++) {
    const processingString = processingStrings[i];
    console.log(`\n[${i + 1}/${processingStrings.length}] Processing: ${processingString}`);
    
    try {
      await processString(clientName, processingString);
    } catch (error) {
      console.error(`❌ Failed to process ${processingString}:`, error.message);
      // Continue with next string instead of stopping entire process
    }
  }

  console.log(`\n🎉 Batch processing completed for client: ${clientName}`);
}

// Export the main function
module.exports = finalBotRuleMetricsTransformConcat;