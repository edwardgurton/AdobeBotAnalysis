const processJSONFilesLegendBotRuleCompare = require('./processJSONFilesLegendBotRuleCompare');
const concatenateCSVs = require('./utils/concatenateCSVs');
const getJsonStorageFolderPath = require('./utils/getJsonStorageFolderPath');
const getCsvStorageFolderPath = require('./utils/getCsvStorageFolderPath');
const path = require('path');

/**
 * Escape special regex characters in a string for safe use in regex patterns
 * @param {string} str - String to escape
 * @returns {string} Escaped string safe for use in regex
 */
function escapeRegexChars(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Process an individual string for bot rule comparison, transformation, and concatenation
 * @param {string} clientName - Name of the client
 * @param {string} processingString - String pattern to process (bot rule name)
 */
async function processString(clientName, processingString) {
  try {
    console.log(`\n=== Starting Bot Rule Compare Process ===`);
    console.log(`Client: ${clientName}`);
    console.log(`Processing String: ${processingString}`);

    // Get folder paths using utility functions
    const jsonFolderPath = getJsonStorageFolderPath(clientName);
    const csvBaseFolderPath = getCsvStorageFolderPath(clientName);

    console.log(`JSON Source Folder: ${jsonFolderPath}`);
    console.log(`CSV Base Folder: ${csvBaseFolderPath}`);

    // Create regex pattern for JSON file matching - escape special characters
    const escapedProcessingString = escapeRegexChars(processingString);
    const jsonPattern = new RegExp(`.*${escapedProcessingString}.*.json$`);
    console.log(`JSON Pattern: ${jsonPattern}`);

    // Define CSV paths - escape processingString for use in regex pattern
    const outputFolderPath = path.join(csvBaseFolderPath, processingString);
    const concatFilePattern = `${escapedProcessingString}.*\\.csv`;
    const outputFilePath = path.join(csvBaseFolderPath, 'BotRuleCompareFinal', `${processingString}.csv`);

    console.log(`CSV Output Folder: ${outputFolderPath}`);
    console.log(`CSV Concat Pattern: ${concatFilePattern}`);
    console.log(`Final Output File: ${outputFilePath}`);

    // Step 1: Process JSON files and wait for completion
    console.log(`\n--- Step 1: Processing JSON Files ---`);
    await processJSONFilesLegendBotRuleCompare(jsonFolderPath, jsonPattern, processingString);
    console.log(`✓ JSON processing completed for ${processingString}`);

    // Step 2: Concatenate CSV files
    console.log(`\n--- Step 2: Concatenating CSV Files ---`);
    await concatenateCSVs(outputFolderPath, concatFilePattern, outputFilePath);
    console.log(`✓ CSV concatenation completed for ${processingString}`);

    console.log(`\n=== Bot Rule Compare Process Complete for ${processingString} ===\n`);

  } catch (error) {
    console.error(`\n✗ Error processing ${processingString}:`, error.message);
    throw error;
  }
}

/**
 * Main processing function for bot rule comparison, transformation, and concatenation
 * @param {string} clientName - Name of the client
 * @param {string[]} processingStrings - Array of bot rule name patterns to process
 */
async function botRuleCompareTransformConcat(clientName, processingStrings) {
  console.log(`\n🚀 Starting batch processing for client: ${clientName}`);
  console.log(`Total bot rules to process: ${processingStrings.length}`);

  for (let i = 0; i < processingStrings.length; i++) {
    const processingString = processingStrings[i];
    console.log(`\n[${i + 1}/${processingStrings.length}] Processing: ${processingString}`);
    
    try {
      await processString(clientName, processingString);
    } catch (error) {
      console.error(`✗ Failed to process ${processingString}:`, error.message);
      // Continue with next string instead of stopping entire process
    }
  }

  console.log(`\n🎉 Batch processing completed for client: ${clientName}`);
}

// Export the main function
module.exports = botRuleCompareTransformConcat;

// Execute if run directly
if (require.main === module) {
  // Example usage with default bot rule names
  const defaultBotRules = [
    '0108-Bot-Rule-Casino.us-Domain-chinamobileltdcom',
    '0109-Bot-Rule-Casino.us-Domain-chinanetcom',
    '0110-Bot-Rule-Casino.us-Domain-chinaunicomcom'
  ];
  
  botRuleCompareTransformConcat('Legend', defaultBotRules)
    .then(() => {
      console.log('✓ All processing completed successfully');
      process.exit(0);
    })
    .catch((error) => {
      console.error('✗ Processing failed:', error);
      process.exit(1);
    });
}