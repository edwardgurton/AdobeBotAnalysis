const processJSONFilesLegendBotInvestigation = require('./processJSONFilesLegendBotInvestigation');
const concatenateCSVs = require('./utils/concatenateCSVs');
const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');
const botInvestigationMinThresholdVisits = require('./usefulinfo/Legend/botInvestigationMinThresholdVisits');
const botInvestigationRsidCountriesMinThreshold = require('./usefulinfo/Legend/botInvestigationRsidCountriesMinThreshold');

/**
 * Helper function to escape regex special characters
 * @param {string} string - String to escape
 * @returns {string} Escaped string safe for use in RegExp
 */
function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Processes bot investigation data by transforming JSON files and concatenating CSVs
 * @param {string} investigationRound - investigation Round to append to output files (not used in mode 3)
 * @param {number} DownloadBatch - 1 for RSIDs, 2 for RSID-Countries, 3 for ad-hoc download
 * @param {Object} adHocOptions - Options for ad-hoc mode (only used when DownloadBatch = 3)
 * @param {string} adHocOptions.botInvestigationPrefix - Prefix to match in file names
 * @returns {Promise<void>}
 */
async function processBotInvestigationData(investigationRound, DownloadBatch, adHocOptions = {}) {
  console.log(`=== Starting Bot Investigation Processing ===`);
  console.log(`Version: V${investigationRound}, Download Batch: ${DownloadBatch}`);

  // Load configuration
  let readWriteConfig;
  try {
    const configPath = path.join(__dirname, 'config/read_write_settings/readWriteSettings.yaml');
    readWriteConfig = yaml.load(fs.readFileSync(configPath, 'utf8'));
    console.log(`✓ Configuration loaded from: ${configPath}`);
  } catch (error) {
    console.error(`✗ Failed to load configuration: ${error.message}`);
    throw error;
  }

  const { folder: baseFolder } = readWriteConfig.storage || {};
  if (!baseFolder) {
    const error = new Error('Base folder is undefined in read/write configuration');
    console.error(`✗ ${error.message}`);
    throw error;
  }

  console.log(`✓ Base folder configured: ${baseFolder}`);

  // Determine processing approach based on DownloadBatch
  let processingList;
  let batchType;
  let isAdHocMode = false;
  
  if (DownloadBatch === 1) {
    processingList = botInvestigationMinThresholdVisits;
    batchType = 'RSIDs';
    console.log(`✓ Processing ${processingList.length} RSIDs`);
  } else if (DownloadBatch === 2) {
    processingList = botInvestigationRsidCountriesMinThreshold.map(item => 
      `${item.rsidCleanName}-${item.geocountry}`
    );
    batchType = 'RSID-Countries';
    console.log(`✓ Processing ${processingList.length} RSID-Country combinations`);
  } else if (DownloadBatch === 3) {
    // Ad-hoc mode validation
    const {botInvestigationPrefix } = adHocOptions;
    
    if (!botInvestigationPrefix) {
      const error = new Error('Ad-hoc mode requires botInvestigationPrefix in adHocOptions');
      console.error(`✗ ${error.message}`);
      throw error;
    }

    isAdHocMode = true;
    batchType = 'Ad-hoc';
    console.log(`✓ Ad-hoc mode - Prefix: ${botInvestigationPrefix}`);
  } else {
    const error = new Error(`Invalid DownloadBatch value: ${DownloadBatch}. Must be 1, 2, or 3`);
    console.error(`✗ ${error.message}`);
    throw error;
  }

  // Setup paths
  const clientName = 'Legend';
  const folderPath = path.join(baseFolder, clientName, 'JSON');
  console.log(`✓ JSON source folder: ${folderPath}`);

  if (isAdHocMode) {
    // Ad-hoc mode processing
    return await processAdHocMode(folderPath, baseFolder, adHocOptions);
  }

  // Regular mode processing (modes 1 and 2)
  let successCount = 0;
  let errorCount = 0;

  for (let i = 0; i < processingList.length; i++) {
    const currentItem = processingList[i];
    console.log(`\n--- Processing ${i + 1}/${processingList.length}: ${currentItem} ---`);

    try {
      // Escape currentItem for safe use in regex patterns
      const escapedCurrentItem = escapeRegExp(currentItem);

      // === DAILY PROCESSING ===
      console.log(`↓ Processing Daily files for ${currentItem}...`);
      
      // Create pattern for Daily JSON file matching
      const dailyPattern = new RegExp(`.*${escapedCurrentItem}-FullRun-V${investigationRound}-Daily.*\\.json$`);
      console.log(`✓ Daily search pattern: ${dailyPattern.source}`);

      // Setup folder for Daily files
      const dailyOptionalFolder = `${currentItem}-V${investigationRound}`;
      console.log(`✓ Daily output folder: ${dailyOptionalFolder}`);

      // Setup Daily concatenation paths
      const dailyOutputFolderPath = path.join(baseFolder, 'Legend', 'CSV', `${currentItem}-V${investigationRound}`);
      const dailyConcatFilePattern = `.*csv`;
      const dailyOutputFilePath = path.join(baseFolder, 'Legend', 'CSV', 'BotInvestigationFinal', `${currentItem}-V${investigationRound}.csv`);
      
      console.log(`✓ Daily CSV source folder: ${dailyOutputFolderPath}`);
      console.log(`✓ Daily final output file: ${dailyOutputFilePath}`);

      // Process Daily JSON files
      await processJSONFilesLegendBotInvestigation(folderPath, dailyPattern, dailyOptionalFolder);
      console.log(`✓ Daily JSON processing completed`);

      // Concatenate Daily CSV files
      console.log(`↓ Concatenating Daily CSV files...`);
      await concatenateCSVs(dailyOutputFolderPath, dailyConcatFilePattern, dailyOutputFilePath, {
        1: 'Feature'
      });
      console.log(`✓ Daily CSV concatenation completed`);

      // === TOTALS PROCESSING ===
      console.log(`↓ Processing Totals files for ${currentItem}...`);
      
      // Create pattern for Totals JSON file matching
      const totalsPattern = new RegExp(`.*_${escapedCurrentItem}-FullRun-V${investigationRound}-Totals.*\\.json$`);
      console.log(`✓ Totals search pattern: ${totalsPattern.source}`);

      // Setup folder for Totals files
      const totalsOptionalFolder = `${currentItem}-FeatureTotals-V${investigationRound}`;
      console.log(`✓ Totals output folder: ${totalsOptionalFolder}`);

      // Setup Totals concatenation paths
      const totalsOutputFolderPath = path.join(baseFolder, 'Legend', 'CSV', `${currentItem}-FeatureTotals-V${investigationRound}`);
      const totalsOutputFilePath = path.join(baseFolder, 'Legend', 'CSV', 'BotInvestigationFinal', `${currentItem}-FeatureTotals-V${investigationRound}.csv`);
      
      console.log(`✓ Totals CSV source folder: ${totalsOutputFolderPath}`);
      console.log(`✓ Totals final output file: ${totalsOutputFilePath}`);

      // Process Totals JSON files
      await processJSONFilesLegendBotInvestigation(folderPath, totalsPattern, totalsOptionalFolder);
      console.log(`✓ Totals JSON processing completed`);

      // Concatenate Totals CSV files
      console.log(`↓ Concatenating Totals CSV files...`);
      await concatenateCSVs(totalsOutputFolderPath, dailyConcatFilePattern, totalsOutputFilePath, {
        1: 'Feature'
      });
      console.log(`✓ Totals CSV concatenation completed`);

      successCount++;
      console.log(`✓ Successfully processed: ${currentItem}`);

    } catch (error) {
      errorCount++;
      console.error(`✗ Failed to process ${currentItem}: ${error.message}`);
      // Continue processing other items rather than stopping
    }
  }

  // Final summary
  console.log(`\n=== Processing Summary ===`);
  console.log(`Batch Type: ${batchType}`);
  console.log(`Version: V${investigationRound}`);
  console.log(`Total Items: ${processingList.length}`);
  console.log(`✓ Successful: ${successCount}`);
  console.log(`✗ Failed: ${errorCount}`);
  
  if (errorCount > 0) {
    console.warn(`⚠ Warning: ${errorCount} items failed to process`);
  } else {
    console.log(`🎉 All items processed successfully!`);
  }

  // === CROSS-ITEM CONCATENATIONS ===
  console.log(`\n=== Starting Cross-Item Concatenations ===`);
  
  try {
    // Cross-item concatenation 1: botInvestigationMetricsByDay
    console.log(`↓ Cross-item concatenation 1: Metrics Per Day...`);
    const csvBasePath = path.join(baseFolder, 'Legend', 'CSV');
    
    // Find all subdirectories that contain the investigation Round
    const allSubdirs = fs.readdirSync(csvBasePath, { withFileTypes: true })
      .filter(dirent => dirent.isDirectory() && dirent.name.includes(investigationRound))
      .map(dirent => path.join(csvBasePath, dirent.name));
    
    console.log(`✓ Found ${allSubdirs.length} subdirectories with version V${investigationRound}`);
    
    // Find files for first concatenation: FullRun-{investigationRound} AND botInvestigationMetricsByDay
    let metricsPerDayFiles = [];
    for (const subdir of allSubdirs) {
      try {
        const files = fs.readdirSync(subdir);
        const matchingFiles = files.filter(file => 
          file.includes(`FullRun-V${investigationRound}`) && 
          file.includes('botInvestigationMetricsByDay')
        );
        metricsPerDayFiles.push(...matchingFiles.map(file => path.join(subdir, file)));
      } catch (err) {
        console.warn(`⚠ Could not read directory ${subdir}: ${err.message}`);
      }
    }
    
    console.log(`✓ Found ${metricsPerDayFiles.length} files for Metrics Per Day concatenation`);
    
    if (metricsPerDayFiles.length > 0) {
      // Create a temporary directory with the files to concatenate
      const tempDir = path.join(csvBasePath, 'temp_metrics_per_day');
      if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir);
      }
      
      // Copy files to temp directory
      for (let i = 0; i < metricsPerDayFiles.length; i++) {
        const srcFile = metricsPerDayFiles[i];
        const fileName = `temp_metrics_${i}_${path.basename(srcFile)}`;
        const destFile = path.join(tempDir, fileName);
        fs.copyFileSync(srcFile, destFile);
      }
      
      const metricsPerDayOutputPath = path.join(baseFolder, 'Legend', 'CSV', 'BotInvestigationFinal', `AllInvestigationsMetricsPerDay-V${investigationRound}.csv`);
      
      await concatenateCSVs(tempDir, '.*csv', metricsPerDayOutputPath, {
        1: 'Feature'
      });
      
      // Clean up temp directory
      fs.rmSync(tempDir, { recursive: true, force: true });
      
      console.log(`✓ Cross-item Metrics Per Day concatenation completed: ${metricsPerDayOutputPath}`);
    } else {
      console.log(`⚠ No files found for Metrics Per Day concatenation`);
    }

    // Cross-item concatenation 2: totals (excluding botInvestigationMetricsByPageURL)
    console.log(`↓ Cross-item concatenation 2: Metrics Per Feature...`);
    
    let metricsPerFeatureFiles = [];
    for (const subdir of allSubdirs) {
      try {
        const files = fs.readdirSync(subdir);
        const matchingFiles = files.filter(file => 
          file.includes(`FullRun-V${investigationRound}`) && 
          file.includes('Totals') &&
          !file.includes('botInvestigationMetricsByPageURL')
        );
        metricsPerFeatureFiles.push(...matchingFiles.map(file => path.join(subdir, file)));
      } catch (err) {
        console.warn(`⚠ Could not read directory ${subdir}: ${err.message}`);
      }
    }
    
    console.log(`✓ Found ${metricsPerFeatureFiles.length} files for Metrics Per Feature concatenation`);
    
    if (metricsPerFeatureFiles.length > 0) {
      // Create a temporary directory with the files to concatenate
      const tempDir = path.join(csvBasePath, 'temp_metrics_per_feature');
      if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir);
      }
      
      // Copy files to temp directory
      for (let i = 0; i < metricsPerFeatureFiles.length; i++) {
        const srcFile = metricsPerFeatureFiles[i];
        const fileName = `temp_feature_${i}_${path.basename(srcFile)}`;
        const destFile = path.join(tempDir, fileName);
        fs.copyFileSync(srcFile, destFile);
      }
      
      const metricsPerFeatureOutputPath = path.join(baseFolder, 'Legend', 'CSV', 'BotInvestigationFinal', `AllInvestigationsMetricsPerFeature-V${investigationRound}.csv`);
      
      await concatenateCSVs(tempDir, '.*csv', metricsPerFeatureOutputPath, {
        1: 'Feature'
      });
      
      // Clean up temp directory
      fs.rmSync(tempDir, { recursive: true, force: true });
      
      console.log(`✓ Cross-item Metrics Per Feature concatenation completed: ${metricsPerFeatureOutputPath}`);
    } else {
      console.log(`⚠ No files found for Metrics Per Feature concatenation`);
    }

    console.log(`\n🎉 All cross-item concatenations completed successfully!`);

  } catch (crossItemError) {
    console.error(`✗ Error during cross-item concatenations: ${crossItemError.message}`);
  }
}

/**
 * Processes ad-hoc bot investigation data based on prefix
 * @param {string} folderPath - Path to JSON files folder
 * @param {string} baseFolder - Base folder path
 * @param {Object} options - Ad-hoc processing options
 * @param {string} options.botInvestigationPrefix - File prefix to match
 */
async function processAdHocMode(folderPath, baseFolder, options) {
  const { botInvestigationPrefix } = options;
  
  console.log(`\n=== Ad-hoc Mode Processing ===`);
    
  try {
    // Get all JSON files in the directory
    const allFiles = fs.readdirSync(folderPath);
    console.log(`✓ Found ${allFiles.length} total files in JSON directory`);
    
    // Filter files based on prefix
    const matchingFiles = allFiles.filter(file => {
      // Must contain the prefix
      if (!file.includes(botInvestigationPrefix)) return false;
      
      // Must be a JSON file
      if (!file.endsWith('.json')) return false;
      
      // If we passed all checks, it's a match
      return true;
    });
    
    console.log(`✓ Found ${matchingFiles.length} matching files for ad-hoc processing`);
    
    if (matchingFiles.length === 0) {
      console.log(`⚠ No files found matching prefix '${botInvestigationPrefix}'`);
      return;
    }
    
    // Log the matching files
    console.log(`↓ Matching files:`);
    matchingFiles.forEach(file => console.log(`  - ${file}`));
    
    // Process files by type (Daily vs Totals)
    const dailyFiles = matchingFiles.filter(file => file.includes('Daily'));
    const totalsFiles = matchingFiles.filter(file => file.includes('Totals'));
    
    console.log(`✓ Found ${dailyFiles.length} Daily files and ${totalsFiles.length} Totals files`);
    
    // Create timestamp for output folder naming
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').split('T')[0];
    const outputSuffix = `${botInvestigationPrefix}-AdHoc-${timestamp}`;
    
    // Process Daily files if any exist
    if (dailyFiles.length > 0) {
      console.log(`\n↓ Processing ${dailyFiles.length} Daily files...`);
      
      // Create pattern that matches any of the daily files - with proper escaping
      const dailyPattern = new RegExp(`(${dailyFiles.map(f => escapeRegExp(f)).join('|')})`);
      const dailyOptionalFolder = `${outputSuffix}-Daily`;
      
      console.log(`✓ Daily output folder: ${dailyOptionalFolder}`);
      
      // Process Daily JSON files
      await processJSONFilesLegendBotInvestigation(folderPath, dailyPattern, dailyOptionalFolder);
      console.log(`✓ Daily JSON processing completed`);
      
      // Concatenate Daily CSV files
      const dailyOutputFolderPath = path.join(baseFolder, 'Legend', 'CSV', dailyOptionalFolder);
      const dailyOutputFilePath = path.join(baseFolder, 'Legend', 'CSV', 'BotInvestigationFinal', `${outputSuffix}-Daily.csv`);
      
      console.log(`↓ Concatenating Daily CSV files...`);
      await concatenateCSVs(dailyOutputFolderPath, '.*csv', dailyOutputFilePath, {
        1: 'Feature'
      });
      console.log(`✓ Daily CSV concatenation completed: ${dailyOutputFilePath}`);
    }
    
    // Process Totals files if any exist
    if (totalsFiles.length > 0) {
      console.log(`\n↓ Processing ${totalsFiles.length} Totals files...`);
      
      // Create pattern that matches any of the totals files - with proper escaping
      const totalsPattern = new RegExp(`(${totalsFiles.map(f => escapeRegExp(f)).join('|')})`);
      const totalsOptionalFolder = `${outputSuffix}-Totals`;
      
      console.log(`✓ Totals output folder: ${totalsOptionalFolder}`);
      
      // Process Totals JSON files
      await processJSONFilesLegendBotInvestigation(folderPath, totalsPattern, totalsOptionalFolder);
      console.log(`✓ Totals JSON processing completed`);
      
      // Concatenate Totals CSV files
      const totalsOutputFolderPath = path.join(baseFolder, 'Legend', 'CSV', totalsOptionalFolder);
      const totalsOutputFilePath = path.join(baseFolder, 'Legend', 'CSV', 'BotInvestigationFinal', `${outputSuffix}-Totals.csv`);
      
      console.log(`↓ Concatenating Totals CSV files...`);
      await concatenateCSVs(totalsOutputFolderPath, '.*csv', totalsOutputFilePath, {
        1: 'Feature'
      });
      console.log(`✓ Totals CSV concatenation completed: ${totalsOutputFilePath}`);
    }
    
    console.log(`\n🎉 Ad-hoc processing completed successfully!`);
    console.log(`✓ Processed ${matchingFiles.length} files for prefix: ${botInvestigationPrefix}`);
    
  } catch (error) {
    console.error(`✗ Error during ad-hoc processing: ${error.message}`);
    throw error;
  }
}

module.exports = processBotInvestigationData;